"""Cross-server enrichment — makes brand-intel the FoundryNet "full company
intelligence" hub.

When domain_profile resolves a domain, we best-effort query sibling Data Network
servers (financial-signals, patent-intel, compliance, oss-intel) for anything they
know about the same company and ride the result along in `network_intelligence`,
at NO extra cost to the buyer. Every call is fail-open: a miss, an error, or a slow
sibling just omits that block — it never blocks or breaks the primary response.

Internal calls carry the fleet `fnet_` bearer (FNET_API_KEY), which bypasses each
sibling's x402 gate, so enrichment between our own servers is free.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from http_util import request_json

logger = logging.getLogger("brand.enrich")

# Fleet bearer for free internal sibling calls (bypasses each sibling's x402 gate).
FNET_KEY = (os.environ.get("FNET_API_KEY")
            or os.environ.get("FORGE_API_KEY")
            or os.environ.get("MINT_API_KEY", "")).strip()

# Sibling REST timeout — short, so enrichment never drags out the primary lookup.
SIB_TIMEOUT = int(os.environ.get("ENRICH_TIMEOUT", "12"))

_GENERIC_SLD = {"www", "mail", "app", "api", "shop", "store", "blog", "go", "get"}


def _sib_url(slug: str, path: str) -> str:
    return f"https://{slug}-mcp-production.up.railway.app{path}"


async def query_sibling(slug: str, path: str, body: dict) -> dict | None:
    """POST a sibling REST endpoint with the fleet bearer (free). Returns the parsed
    JSON dict, or None on any error/non-dict/error-body."""
    headers = {"Content-Type": "application/json"}
    if FNET_KEY:
        headers["Authorization"] = f"Bearer {FNET_KEY}"
    try:
        data = await request_json("POST", _sib_url(slug, path),
                                  headers=headers, body=body, timeout=SIB_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        logger.info(f"enrich {slug}{path} failed: {e}")
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    return data


def guess_company_name(profile: dict) -> str:
    """Best-effort company name from the domain's second-level label
    (e.g. 'tesla.com' → 'tesla'). Skips generic subdomain labels."""
    dom = (profile.get("domain") or "").strip().lower()
    if not dom:
        return ""
    label = dom.split(".")[0]
    if label in _GENERIC_SLD:
        parts = dom.split(".")
        label = parts[1] if len(parts) > 1 else label
    return label


def guess_ticker(name: str) -> str | None:
    """Crude ticker guess (uppercased alpha SLD, ≤5 chars). Most lookups will miss
    and be omitted — financial enrichment only lands on an exact ticker match."""
    if not name:
        return None
    s = re.sub(r"[^A-Za-z]", "", name).upper()
    return s[:5] if 1 <= len(s) <= 5 else None


async def enrich_profile(profile: dict) -> dict:
    """Gather best-effort cross-server intelligence for the profile's company.
    Returns an enrichment dict (possibly empty). Never raises."""
    name = guess_company_name(profile)
    if not name:
        return {}
    ticker = guess_ticker(name)

    async def _noop():
        return None

    jobs = {
        "financial": (query_sibling("financial-signals", "/v1/company", {"ticker": ticker})
                      if ticker else _noop()),
        "patents": query_sibling("patent-intel", "/v1/company",
                                 {"company_name": name, "days_back": 365}),
        "compliance": query_sibling("compliance", "/v1/search",
                                    {"keyword": name, "days_back": 90}),
        "oss": query_sibling("oss-intel", "/v1/dependency-risk",
                             {"package_name": name, "ecosystem": "npm"}),
    }
    keys = list(jobs)
    settled = await asyncio.gather(*jobs.values(), return_exceptions=True)
    got = {k: (v if not isinstance(v, Exception) else None) for k, v in zip(keys, settled)}

    enrichment: dict = {}

    fin = got.get("financial")
    if isinstance(fin, dict) and fin.get("composite_value_score") is not None:
        enrichment["financial"] = {
            "ticker": fin.get("ticker"),
            "company": fin.get("company"),
            "composite_value_score": fin.get("composite_value_score"),
            "insider_activity_summary": fin.get("insider_summary"),
            "earnings_beat_streak": (fin.get("earnings_track_record") or {}).get("beat_streak"),
        }

    pat = got.get("patents")
    if isinstance(pat, dict) and (pat.get("patent_count") or 0) > 0:
        enrichment["patents"] = {
            "total_patents": pat.get("patent_count"),
            "filing_velocity_90d": pat.get("filing_velocity_90d"),
            "primary_cpc": [a.get("cpc") for a in (pat.get("primary_technology_areas") or [])][:5],
        }

    comp = got.get("compliance")
    if isinstance(comp, dict) and comp.get("results"):
        results = comp.get("results") or []
        sev: dict = {}
        for r in results:
            s = (r.get("severity") or "unspecified")
            sev[s] = sev.get(s, 0) + 1
        enrichment["compliance"] = {
            "recent_actions": len(results),
            "severity_summary": sev,
        }

    oss = got.get("oss")
    if isinstance(oss, dict) and (oss.get("risk_score") is not None
                                  or oss.get("known_vulnerabilities") is not None):
        enrichment["open_source_risk"] = {
            "package": name, "ecosystem": "npm",
            "risk_score": oss.get("risk_score"),
            "known_vulnerabilities": oss.get("known_vulnerabilities"),
        }

    return enrichment
