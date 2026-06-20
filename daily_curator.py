"""Daily curated brief — brand-intel.

Runs once a day at BRIEF_HOUR_UTC (05:00 UTC) as an in-process background task
(same shape as the stale-refresh loop). It summarizes the last 24h of cache
activity, surfaces notable findings, flags cached domains whose SSL certs expire
soon, attests the package through MINT for verifiable provenance, and upserts it
into the `daily_briefs` table. The paid `daily_brief` tool just reads that row
back. This is an on-demand cache, so the brief may be small — that's acceptable.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import mint_integration
import supa

logger = logging.getLogger("brand.curator")

SERVER = config.SERVER_SLUG
PRICE = config.PRICE_DAILY_BRIEF


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _expires_at(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")


def related_briefs(exclude: str) -> list:
    return [{"server": s, "price": p, "tool": "daily_brief"}
            for s, p in config.NETWORK_BRIEFS.items() if s != exclude]


async def _curate_signals(since_iso: str) -> tuple[dict, int]:
    """Build the brand-intel brief body from the cache. Returns (signals, count)."""
    now = datetime.now(timezone.utc)

    # ── Cache activity in the last 24h (rows checked since `since_iso`) ──────────
    recent = await supa.select("brand_intel", {
        "select": ("domain,registrar,registration_date,enrich_level,cms,"
                   "hosting_provider,industry_estimate,last_checked,created_at"),
        "last_checked": f"gte.{since_iso}", "order": "last_checked.desc",
        "limit": "500"})
    new_domains = [r for r in recent if (r.get("created_at") or "") >= since_iso]
    full = [r for r in recent if r.get("enrich_level") == "full"]
    activity_summary = {
        "domains_touched_24h": len(recent),
        "newly_profiled_24h": len(new_domains),
        "full_enrichments_24h": len(full),
        "whois_only_24h": len(recent) - len(full),
    }

    # ── Notable findings: newly registered domains + interesting tech/CMS ───────
    young_cutoff = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
    notable_findings = []
    for r in recent:
        reg = r.get("registration_date")
        if reg and reg >= young_cutoff:
            notable_findings.append({"domain": r.get("domain"), "finding": "recently_registered",
                                     "registration_date": reg, "registrar": r.get("registrar")})
    for r in recent:
        if r.get("cms") or r.get("hosting_provider"):
            notable_findings.append({"domain": r.get("domain"), "finding": "tech_detected",
                                     "cms": r.get("cms"), "hosting_provider": r.get("hosting_provider"),
                                     "industry_estimate": r.get("industry_estimate")})
    notable_findings = notable_findings[:10]

    # ── Cached domains whose SSL certs expire in the next 30 days ────────────────
    soon = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    expiring = await supa.select("brand_intel", {
        "select": "domain,ssl_issuer,ssl_expiry",
        "ssl_expiry": f"lte.{soon}", "order": "ssl_expiry.asc", "limit": "20"})
    nowstr = now.strftime("%Y-%m-%dT%H:%M:%S")
    expiring_ssl_certs = [{"domain": r.get("domain"), "ssl_issuer": r.get("ssl_issuer"),
                           "ssl_expiry": r.get("ssl_expiry")}
                          for r in expiring if (r.get("ssl_expiry") or "") >= nowstr]

    signals = {
        "activity_summary": activity_summary,
        "notable_findings": notable_findings,
        "expiring_ssl_certs": expiring_ssl_certs,
    }
    count = len(new_domains) + len(notable_findings) + len(expiring_ssl_certs)
    return signals, count


async def run_curation(date_str: str | None = None) -> dict:
    """Generate, attest, and store today's brief. Idempotent per date (upsert)."""
    date_str = date_str or _today()
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    signals, count = await _curate_signals(since_iso)

    brief = {
        "brief_date": date_str, "server": SERVER, "signal_count": count,
        "signals": signals, "expires_at": _expires_at(date_str),
        "related_briefs": related_briefs(SERVER),
    }
    # Attest for provenance (sync httpx → run off the event loop; fail-open).
    attestation = await asyncio.to_thread(
        mint_integration.attest_data, brief, "analysis",
        f"Daily {SERVER} brief: {count} signals")
    brief["provenance"] = attestation

    row = {
        "brief_date": date_str, "brief_data": brief, "signal_count": count,
        "attestation_hash": attestation.get("attestation_hash"),
        "expires_at": _expires_at(date_str),
    }
    res = await supa.upsert("daily_briefs", [row], "brief_date")
    if isinstance(res, dict) and res.get("error"):
        logger.warning(f"daily brief upsert failed: {str(res)[:200]}")
    else:
        logger.info(f"daily brief stored: {date_str} ({count} signals, "
                    f"attested={attestation.get('mint_verified')})")
    return brief


async def get_brief(date_str: str | None = None) -> dict | None:
    """Read a stored brief; None if missing or expired."""
    date_str = date_str or _today()
    rows = await supa.select("daily_briefs",
                             {"select": "*", "brief_date": f"eq.{date_str}", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return None
        except Exception:  # noqa: BLE001
            pass
    return row.get("brief_data")


async def bump_purchase(date_str: str) -> None:
    """Best-effort purchase counter via RPC (no-op if the function is absent)."""
    try:
        await supa.rpc("increment_brief_purchase", {"p_brief_date": date_str})
    except Exception:  # noqa: BLE001
        pass


async def curator_loop() -> None:
    """Sleep until BRIEF_HOUR_UTC each day, then curate. Cancellable."""
    while True:
        now = datetime.now(timezone.utc)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wait = (config.BRIEF_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await run_curation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"curator loop error: {e}")
            await asyncio.sleep(3600)
