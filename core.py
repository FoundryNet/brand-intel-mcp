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
import enrich
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
    return {"profile": _profile_view(row), "billing": _billing(decision)}


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
