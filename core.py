"""Shared logic behind the MCP tools and REST routes: the on-demand cache plus the
four operations. Cache rule: a domain that's missing, stale (>CACHE_TTL_DAYS), or
not yet fully enriched triggers a live enrich; otherwise the cached row is served.
Enrichment (blocking WHOIS/DNS/HTTP) runs in a worker thread.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
import daily_curator
import enrich
import mint_integration
import network_enrich
import payment_gate
import supa

logger = logging.getLogger("brand.core")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _is_fresh(row: Optional[dict]) -> bool:
    if not row:
        return False
    lc = _parse(row.get("last_checked"))
    return bool(lc and (_now() - lc) <= timedelta(days=config.CACHE_TTL_DAYS))


def _billing(decision: dict) -> dict:
    g = decision.get("gate")
    if g == "free":
        cap, cnt = decision.get("cap"), decision.get("count")
        return {"tier": "free", "used_today": cnt, "daily_free": cap,
                "remaining_today": (cap - cnt) if (cap is not None and cnt is not None) else None}
    if g == "paid":
        return {"tier": "paid", "charged_usdc": decision.get("amount_usdc")}
    if g == "api_key":
        return {"tier": "api_key", "note": "billed to your Forge account"}
    return {"tier": "free", "note": "gating inert"}


async def get_or_enrich(domain: str, *, need_full: bool) -> dict:
    """Return a brand_intel row for `domain`, enriching live on miss/stale/insufficient."""
    domain = enrich._norm_domain(domain)
    row = await supa.get_domain(domain)
    have_full = bool(row and row.get("enrich_level") == "full" and row.get("tech_stack") is not None)
    if _is_fresh(row) and (have_full or not need_full):
        return {**row, "cache": "hit"}

    do_full = need_full or have_full
    newrow = await asyncio.to_thread(enrich.enrich_domain, domain, full=do_full)
    res = await supa.upsert_domain(newrow)
    if "error" in res:
        logger.warning(f"upsert {domain} failed: {res}")
    merged = {**(row or {}), **newrow, "cache": "miss"}
    return merged


# ── operations ────────────────────────────────────────────────────────────────
_PROFILE_FIELDS = (
    "domain", "registrar", "registration_date", "expiry_date", "nameservers",
    "ssl_issuer", "ssl_expiry", "tech_stack", "cms", "hosting_provider",
    "wayback_first_snapshot", "wayback_total_snapshots", "social_twitter",
    "social_linkedin", "social_github", "employee_estimate", "industry_estimate",
    "last_checked",
)


def _profile_view(row: dict) -> dict:
    out = {k: row.get(k) for k in _PROFILE_FIELDS}
    out["cache"] = row.get("cache")
    return out


async def do_profile(domain: str, *, agent_key: str, payment_tx=None, api_key=None) -> dict:
    if not domain:
        return {"error": "bad_request", "detail": "domain is required"}
    price = config.PRICE_DOMAIN_PROFILE
    d = enrich._norm_domain(domain)
    decision = await payment_gate.precheck("domain_profile", {"domain": d}, price,
                                           agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    row = await get_or_enrich(d, need_full=True)
    result = {"profile": _profile_view(row), "billing": _billing(decision)}
    # Cross-server enrichment — query siblings for the same company and ride the
    # result along at no extra cost (best-effort; fail-open; never blocks).
    try:
        enrichment = await network_enrich.enrich_profile(result["profile"])
    except Exception as e:  # noqa: BLE001
        logger.info(f"network enrichment skipped: {e}")
        enrichment = {}
    if enrichment:
        result["network_intelligence"] = enrichment
        result["enrichment_note"] = "Auto-enriched from the FoundryNet Data Network"
    # Provenance attestation (additive; fail-open; off the event loop).
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, result, "analysis", "domain_profile query result")
    return result


async def do_tech(domain: str, *, agent_key: str, payment_tx=None, api_key=None) -> dict:
    if not domain:
        return {"error": "bad_request", "detail": "domain is required"}
    price = config.PRICE_TECH_STACK
    d = enrich._norm_domain(domain)
    decision = await payment_gate.precheck("tech_stack", {"domain": d}, price,
                                           agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    row = await get_or_enrich(d, need_full=True)
    return {"domain": d, "tech_stack": row.get("tech_stack") or [],
            "cms": row.get("cms"), "hosting_provider": row.get("hosting_provider"),
            "cache": row.get("cache"), "billing": _billing(decision)}


async def do_age(domain: str) -> dict:
    """FREE — registration date, age, expiry. Triggers a cheap WHOIS-only enrich on
    cache miss (cached, so repeat calls are free of work)."""
    if not domain:
        return {"error": "bad_request", "detail": "domain is required"}
    d = enrich._norm_domain(domain)
    row = await get_or_enrich(d, need_full=False)
    reg = _parse(row.get("registration_date"))
    exp = _parse(row.get("expiry_date"))
    now = _now()
    return {
        "domain": d,
        "registration_date": row.get("registration_date"),
        "age_days": (now - reg).days if reg else None,
        "expiry_date": row.get("expiry_date"),
        "expires_in_days": (exp - now).days if exp else None,
        "cache": row.get("cache"),
    }


async def do_batch(domains: list, *, agent_key: str, payment_tx=None, api_key=None) -> dict:
    if not domains or not isinstance(domains, list):
        return {"error": "bad_request", "detail": "domains (non-empty array) is required"}
    norm = sorted({enrich._norm_domain(x) for x in domains if x})[:50]
    if not norm:
        return {"error": "bad_request", "detail": "no valid domains"}
    price = max(config.PRICE_BATCH_MIN, round(config.PRICE_BATCH_PER_DOMAIN * len(norm), 6))
    decision = await payment_gate.precheck("batch_enrich", {"domains": norm}, price,
                                           agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    # Enrich concurrently (each get_or_enrich offloads blocking work to a thread).
    rows = await asyncio.gather(*[get_or_enrich(d, need_full=True) for d in norm],
                                return_exceptions=True)
    profiles = []
    for d, r in zip(norm, rows):
        if isinstance(r, Exception):
            profiles.append({"domain": d, "error": str(r)})
        else:
            profiles.append(_profile_view(r))
    return {"results": profiles, "count": len(profiles),
            "price_usdc": price, "billing": _billing(decision)}


# ── daily_brief (premium, curated) ────────────────────────────────────────────
async def do_daily_brief(date, *, agent_key, payment_tx=None, api_key=None) -> dict:
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    decision = await payment_gate.precheck("daily_brief", {"date": day},
                                           config.PRICE_DAILY_BRIEF, agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                          f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                "billing": _billing(decision)}
    await daily_curator.bump_purchase(day)
    return {**brief, "billing": _billing(decision)}


# ── daily refresh (background task + brand_aggregator cron) ───────────────────
async def refresh_stale(limit: int = 200) -> int:
    """Re-enrich the oldest cached domains past the TTL. Returns count refreshed."""
    before = (_now() - timedelta(days=config.CACHE_TTL_DAYS)).isoformat()
    domains = await supa.stale_domains(before, limit)
    n = 0
    for d in domains:
        try:
            newrow = await asyncio.to_thread(enrich.enrich_domain, d, full=True)
            await supa.upsert_domain(newrow)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.info(f"refresh {d} failed: {e}")
    logger.info(f"refresh_stale: refreshed {n}/{len(domains)} stale domains")
    return n


def mint_info() -> dict:
    """FoundryNet Data Network + MINT Protocol attestation details (free)."""
    return {
        "network": "FoundryNet Data Network", **mint_integration.network_feed_block(),
        "message": ("Attest your agent's domain/brand intelligence analysis with MINT "
                    "Protocol for verifiable on-chain proof of work."),
        "mint_protocol": {"mcp_endpoint": "https://mint-mcp-production.up.railway.app/mcp",
                          "info_url": "https://mint.foundrynet.io",
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }


# ── Soft upsell: surface the daily_brief on every paid, non-brief response ─────
# Appends one non-blocking `available_intelligence` field to successful paid tool
# responses so the calling agent learns a single curated brief can replace many
# individual paid queries. Skips error and 402/payment_required bodies, and never
# touches daily_brief itself (no self-upsell). Brief status is cached 5 min, so
# this adds no per-call DB latency. Added 2026-06-20 (seller_agent v2 upsell hook).
import time as _upsell_time

_brief_upsell_cache = {"day": None, "ts": 0.0, "available": False, "count": 0}


async def _brief_status_cached() -> tuple[bool, int]:
    day = _upsell_time.strftime("%Y-%m-%d", _upsell_time.gmtime())
    now = _upsell_time.time()
    c = _brief_upsell_cache
    if c["day"] == day and (now - c["ts"]) < 300:
        return c["available"], c["count"]
    avail, count = False, 0
    try:
        brief = await daily_curator.get_brief(day)
        if brief:
            avail, count = True, int(brief.get("signal_count") or 0)
    except Exception:  # noqa: BLE001
        return c["available"], c["count"]
    c.update(day=day, ts=now, available=avail, count=count)
    return avail, count


async def _available_intelligence() -> dict:
    avail, count = await _brief_status_cached()
    return {"daily_brief": {
        "available": avail,
        "signal_count": count,
        "price_usd": config.PRICE_DAILY_BRIEF,
        "tool": "daily_brief",
        "note": "Curated daily intelligence — more efficient than individual queries",
    }}


def _make_upsell(_fn):
    import functools

    @functools.wraps(_fn)
    async def _wrapped(*a, **k):
        result = await _fn(*a, **k)
        if isinstance(result, dict) and "error" not in result and "payment_required" not in result:
            try:
                result["available_intelligence"] = await _available_intelligence()
            except Exception:  # noqa: BLE001
                pass
            try:
                import asyncio as _aio, mint_integration as _mint
                result["foundrynet_network"] = await _aio.to_thread(_mint.network_heartbeat)
            except Exception:  # noqa: BLE001
                pass
        return result

    return _wrapped


for _upsell_fn in ("do_profile", "do_tech", "do_batch",):
    if _upsell_fn in globals():
        globals()[_upsell_fn] = _make_upsell(globals()[_upsell_fn])
