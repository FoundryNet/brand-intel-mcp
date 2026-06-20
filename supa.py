"""Supabase PostgREST client for brand-intel-mcp (standalone brand-intel project).

Backs the brand_intel cache, the free-tier counter (brand_claim_free_query RPC),
and the x402 payment ledger (brand_payments). Every helper returns plain data and
never raises — failures degrade to None/[]/{}/False.
"""
from __future__ import annotations

import logging
from typing import Optional

import config
from http_util import request_json

logger = logging.getLogger("brand.supa")


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
         "Content-Type": "application/json", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{path}"


async def _select(table: str, params: dict) -> list:
    if not configured():
        return []
    r = await request_json("GET", _url(table), headers=_headers(),
                           params=params, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return r
    logger.warning(f"supa select {table} failed: {r}")
    return []


async def _rpc(fn: str, body: dict):
    if not configured():
        return None
    return await request_json("POST", _url(f"rpc/{fn}"), headers=_headers(),
                              body=body, timeout=config.REQUEST_TIMEOUT)


# ── brand_intel cache ─────────────────────────────────────────────────────────
async def get_domain(domain: str) -> Optional[dict]:
    rows = await _select("brand_intel", {"domain": f"eq.{domain}", "select": "*", "limit": "1"})
    return rows[0] if rows else None


async def upsert_domain(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("brand_intel"),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=representation"}),
                           params={"on_conflict": "domain"},
                           body=[row], timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return {"data": r}
    return r if isinstance(r, dict) else {"error": "bad_response", "detail": str(r)}


async def stale_domains(before_iso: str, limit: int = 200) -> list:
    """Domains whose cache is older than before_iso — the daily refresh worklist."""
    rows = await _select("brand_intel", {
        "select": "domain", "last_checked": f"lt.{before_iso}",
        "order": "last_checked.asc", "limit": str(limit)})
    return [r["domain"] for r in rows if r.get("domain")]


# ── generic helpers (daily_curator) ──────────────────────────────────────────
async def select(table: str, params: dict) -> list:
    """Generic PostgREST GET. Returns a list (empty on failure)."""
    return await _select(table, params)


async def upsert(table: str, rows: list, on_conflict: str) -> dict:
    """Generic merge-duplicates upsert. Returns {"data": [...]} or {"error": ...}."""
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url(table),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=representation"}),
                           params={"on_conflict": on_conflict},
                           body=rows, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return {"data": r}
    return r if isinstance(r, dict) else {"error": "bad_response", "detail": str(r)}


async def rpc(fn: str, body: dict):
    return await _rpc(fn, body)


# ── free-tier counter ─────────────────────────────────────────────────────────
async def claim_free_query(agent_key: str, day: str, cap: int) -> Optional[dict]:
    r = await _rpc("brand_claim_free_query",
                   {"p_agent_key": agent_key, "p_day": day, "p_cap": cap})
    if isinstance(r, dict) and "allowed" in r:
        return r
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0]
    logger.warning(f"claim_free_query rpc unexpected: {r}")
    return None


# ── payment ledger ────────────────────────────────────────────────────────────
async def payment_tx_used(tx_signature: str) -> bool:
    rows = await _select("brand_payments",
                         {"tx_signature": f"eq.{tx_signature}", "select": "tx_signature", "limit": "1"})
    return bool(rows)


async def insert_payment(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("brand_payments"),
                           headers=_headers({"Prefer": "return=minimal"}),
                           body=row, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return {"data": r}
    if isinstance(r, dict) and "error" not in r:
        return {"data": [r]}
    return r if isinstance(r, dict) else {"error": "bad_response", "detail": str(r)}
