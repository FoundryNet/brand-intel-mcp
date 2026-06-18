"""brand-intel-mcp — domain & brand intelligence for autonomous agents.

A FastMCP server with an on-demand cache over its OWN standalone Supabase project.
On a query for a domain that's missing or stale (>7d) it enriches live from free
sources (WHOIS, DNS, CT logs, Wayback, tech-stack heuristics, socials) and caches
the result; otherwise it serves the cache. A daily background task refreshes stale
rows (the brand_aggregator role, in-process).

  domain_profile   — full brand intelligence profile        ($0.02)
  tech_stack       — detected technologies / CMS / hosting   ($0.01)
  domain_age       — registration date, age, expiry          (free)
  batch_enrich     — array of profiles, the volume play      ($0.01/domain, min $0.05)

Free tier 10 queries/day per agent, then x402 (USDC on Solana). Bearer fnet_ key
bypasses. Transport: Streamable HTTP at /mcp (+ legacy /sse). Health: /health.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import core
import identity
import payment_gate
import supa
import tools

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("brand.mcp")

if not supa.configured():
    logger.warning("SUPABASE_SERVICE_KEY not set — cache disabled; live enrichment "
                   "still works but nothing is persisted.")

mcp = FastMCP("brand-intel")

if payment_gate.is_active():
    logger.info(f"pay-per-query ARMED → {config.PAYMENT_RECIPIENT} after "
                f"{config.FREE_TIER_DAILY}/day free (profile=${config.PRICE_DOMAIN_PROFILE}, "
                f"tech=${config.PRICE_TECH_STACK}, batch=${config.PRICE_BATCH_PER_DOMAIN}/domain)")
else:
    logger.info("pay-per-query INERT (X402 off or recipient unset) — all tools free")

tools.register_all(mcp)


# ── Health ──────────────────────────────────────────────────────────────────
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok", "service": "brand-intel-mcp", "transport": "streamable-http",
        "tools": ["domain_profile", "tech_stack", "domain_age", "batch_enrich"],
        "cache": "supabase:brand_intel" if supa.configured() else "unconfigured",
        "cache_ttl_days": config.CACHE_TTL_DAYS,
        "x402_enabled": config.X402_ENABLED,
        "query_payment": "armed" if payment_gate.is_active() else "free",
        "prices_usdc": {"domain_profile": config.PRICE_DOMAIN_PROFILE,
                        "tech_stack": config.PRICE_TECH_STACK,
                        "batch_per_domain": config.PRICE_BATCH_PER_DOMAIN,
                        "batch_min": config.PRICE_BATCH_MIN},
        "free_tier_daily": config.FREE_TIER_DAILY,
        "payment_recipient": config.PAYMENT_RECIPIENT,
        "payment_ledger": "supabase" if supa.configured() else "in_memory",
    })


@mcp.custom_route("/ping", methods=["GET"])
async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── REST surface ─────────────────────────────────────────────────────────────
_ERR_STATUS = {"bad_request": 400, "not_configured": 503, "not_found": 404,
               "payment_required": 402}


def _resp(d: dict) -> JSONResponse:
    if "error" not in d:
        return JSONResponse(d, status_code=200)
    err = str(d.get("error") or "")
    code = _ERR_STATUS.get(err, 502 if err in ("network", "non_json_response", "unreachable") else 400)
    if err.startswith("http_") and err[5:].isdigit():
        code = int(err[5:])
    return JSONResponse(d, status_code=code)


async def _json_body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _akey(request: Request, body: dict) -> str:
    return identity.resolve_agent_key(body.get("agent_id"), request=request)


@mcp.custom_route("/v1/profile", methods=["POST"])
async def rest_profile(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_profile(b.get("domain", ""), agent_key=_akey(request, b),
                                       payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/tech", methods=["POST"])
async def rest_tech(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_tech(b.get("domain", ""), agent_key=_akey(request, b),
                                    payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/age", methods=["POST"])
async def rest_age(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_age(b.get("domain", "")))


@mcp.custom_route("/v1/batch", methods=["POST"])
async def rest_batch(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_batch(b.get("domains", []), agent_key=_akey(request, b),
                                     payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


# ── Discovery ────────────────────────────────────────────────────────────────
_AGENT_CARD = {
    "name": "Brand Intelligence MCP",
    "description": ("Domain & brand intelligence for agents: company enrichment, "
                    "domain intelligence, tech stack detection, and brand research "
                    "from WHOIS, DNS, CT logs, Wayback, and tech fingerprinting."),
    "url": "https://github.com/FoundryNet/brand-intel-mcp",
    "capabilities": ["company_enrichment", "domain_intelligence",
                     "tech_stack_detection", "brand_research"],
    "protocols": {
        "mcp": {"endpoint": config.PUBLIC_MCP_URL, "transport": "streamable-http", "tools_count": 4},
        "x402": {"supported": True, "currency": "USDC", "network": "solana"},
    },
    "contact": "hello@foundrynet.io",
}


@mcp.custom_route("/.well-known/agent-card.json", methods=["GET"])
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_AGENT_CARD, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/.well-known/mcp", methods=["GET"])
async def mcp_endpoints(request: Request) -> JSONResponse:
    return JSONResponse({"endpoints": [{"url": config.PUBLIC_MCP_URL,
                                        "transport": "streamable-http",
                                        "name": "Brand Intelligence MCP"}]},
                        headers={"Cache-Control": "public, max-age=300"})


async def _live_tools() -> list:
    res = mcp.list_tools()
    if inspect.iscoroutine(res):
        res = await res
    return [{"name": t.name, "description": (getattr(t, "description", "") or "").strip(),
             "inputSchema": getattr(t, "parameters", None) or {"type": "object"}} for t in res]


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    live = await _live_tools()
    return JSONResponse({
        "serverInfo": {"name": "Brand Intelligence MCP", "version": "1.0.0"},
        "authentication": {"type": "http", "scheme": "bearer",
                           "description": ("domain_age is free; other tools give 10 free "
                                           "queries/day then take an fnet_ Bearer key OR x402 USDC.")},
        "tools": live,
        "version": "1.0", "name": "Brand Intelligence MCP",
        "tagline": "Company enrichment & domain intelligence for agents.",
        "description": ("Domain & brand intelligence: company enrichment, domain "
                        "intelligence, tech stack detection, and brand research. WHOIS, "
                        "DNS, SSL/CT logs, Wayback history, tech fingerprinting, and "
                        "socials — cached, with a free tier then 2¢/profile via x402."),
        "serverUrl": config.PUBLIC_MCP_URL, "transport": "streamable-http",
        "tools_count": len(live),
        "categories": ["data", "enrichment", "intelligence", "research", "sales"],
        "pricing": {"model": "metered",
                    "free_tier": f"{config.FREE_TIER_DAILY} queries/day per agent + free domain_age",
                    "paid_from": f"{config.PRICE_TECH_STACK} USDC per query (x402)"},
    }, headers={"Cache-Control": "public, max-age=300"})


# ── Entrypoint ───────────────────────────────────────────────────────────────
async def _refresh_loop():
    """Daily background refresh of stale cache rows (the brand_aggregator role)."""
    interval = max(1, config.REFRESH_INTERVAL_HOURS) * 3600
    while True:
        try:
            await asyncio.sleep(interval)
            if supa.configured():
                await core.refresh_stale()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"refresh loop error: {e}")


def build_dual_app():
    main_app = mcp.http_app(transport="http", path="/mcp")
    sse_app = mcp.http_app(transport="sse", path="/sse")
    for r in sse_app.routes:
        if getattr(r, "path", None) in ("/sse", "/messages"):
            main_app.router.routes.append(r)
    main_life, sse_life = main_app.router.lifespan_context, sse_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _dual_lifespan(app):
        async with main_life(app):
            async with sse_life(app):
                task = asyncio.create_task(_refresh_loop())
                try:
                    yield
                finally:
                    task.cancel()
                    with contextlib.suppress(Exception):
                        await task
    main_app.router.lifespan_context = _dual_lifespan
    return main_app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"brand-intel-mcp starting on 0.0.0.0:{config.PORT} "
                f"(cache={'supabase' if supa.configured() else 'off'}, x402={config.X402_ENABLED})")
    uvicorn.run(build_dual_app(), host="0.0.0.0", port=config.PORT, log_level="warning")
