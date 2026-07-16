"""Env-driven configuration for brand-intel-mcp.

A domain & brand-intelligence MCP server with an on-demand cache: on a query for a
domain that's missing or stale (>CACHE_TTL_DAYS) it enriches live (WHOIS, DNS, CT
logs, Wayback, tech stack, socials) and caches the result in its OWN standalone
Supabase project; otherwise it returns the cache. Three of four tools are paid via
x402 (USDC on Solana); domain_age is free. A free tier precedes the paywall.

Required to be useful:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   the standalone brand-intel Supabase project.
Optional:
  PORT, REQUEST_TIMEOUT
  X402_ENABLED            "true" arms the paywall (DEFAULT true; kill switch)
  SOLANA_WALLET           base58 operations wallet (gate inert until set)
  PAYMENT_RECIPIENT       defaults to SOLANA_WALLET
  PAYMENT_VERIFY_RPC      Solana JSON-RPC for on-chain payment confirmation
  PAYMENT_USDC_MINT       SPL mint accepted (default USDC mainnet)
  PAYMENT_EXPIRY_SECONDS  payment freshness / replay window, default 300
  FREE_TIER_DAILY         free paid-tool queries/day per agent, default 5
  CACHE_TTL_DAYS          cache freshness window, default 7
  PRICE_DOMAIN_PROFILE    default 0.02
  PRICE_TECH_STACK        default 0.01
  PRICE_BATCH_PER_DOMAIN  default 0.01
  PRICE_BATCH_MIN         default 0.05
  REFRESH_INTERVAL_HOURS  daily background stale-refresh cadence, default 24
  PUBLIC_MCP_URL
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


# ── Standalone brand-intel Supabase (NOT the core Foundry project) ────────────
SUPABASE_URL         = _env("SUPABASE_URL", "https://irqpkttocandqsgcuutw.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")
# Shared-hub consolidation: which Postgres schema this service's tables live in.
# "public" = standalone; a service name (e.g. "brand") = the shared intel hub,
# reached via PostgREST Accept-Profile/Content-Profile headers.
SUPABASE_SCHEMA      = _env("SUPABASE_SCHEMA", "public")

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

CACHE_TTL_DAYS  = int(_env("CACHE_TTL_DAYS", "7"))
REFRESH_INTERVAL_HOURS = int(_env("REFRESH_INTERVAL_HOURS", "24"))

# ── x402 pay-per-query gate (per-tool pricing) ───────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWJjfn27VQhTXd1jUNTzszCmsErkzaEeHWbLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "5"))

# $0.05 (up from $0.02): domain_profile now rides cross-server enrichment from up
# to five sibling Data Network servers (financial, patents, compliance, OSS, cyber)
# — five+ data sources in one call justify the premium.
PRICE_DOMAIN_PROFILE   = float(_env("PRICE_DOMAIN_PROFILE", "0.05"))
PRICE_TECH_STACK       = float(_env("PRICE_TECH_STACK", "0.01"))
PRICE_BATCH_PER_DOMAIN = float(_env("PRICE_BATCH_PER_DOMAIN", "0.01"))
PRICE_BATCH_MIN        = float(_env("PRICE_BATCH_MIN", "0.05"))
PRICE_DAILY_BRIEF      = float(_env("PRICE_DAILY_BRIEF", "5"))
PRICE_BRIEF_SUMMARY = float(_env("PRICE_BRIEF_SUMMARY", "0.5"))  # $0.50 sample tier

# ── Stripe rail (parallel payment option to x402, for the daily brief) ────────
# Agents without a USDC wallet pay this hosted Payment Link instead. The secret
# key verifies the resulting Checkout Session; the link URL is shown on a 402.
STRIPE_SECRET_KEY       = _env("STRIPE_SECRET_KEY", "")
STRIPE_LINK_DAILY_BRIEF = _env("STRIPE_LINK_DAILY_BRIEF",
                               "https://foundrynet.io/pricing")

# ── Daily curated brief ──────────────────────────────────────────────────────
BRIEF_HOUR_UTC = int(_env("BRIEF_HOUR_UTC", "5"))   # curator runs at 05:00 UTC
SERVER_SLUG    = "brand-intel"
# Cross-network brief catalog (server -> price + tool) for related_briefs.
NETWORK_BRIEFS = {
    "financial-signals": "$25", "cyber-intel": "$15", "patent-intel": "$10",
    "gov-contracts": "$10", "compliance": "$10", "brand-intel": "$5", "weather-intel": "$5",
}

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://brand-intel-mcp-production.up.railway.app/mcp")

# ── FoundryNet Data Network — full sister-server map (auto-updated 2026-06-19) ──
# Re-binds SISTER_SERVERS to the complete network (all 11 servers, self excluded),
# now including fact-check-mcp, oss-intel-mcp, social-intel-mcp.
_FNET_ALL_SERVERS = {
    "mint-mcp":              "https://mint-mcp-production.up.railway.app/mcp",
    "foundrynet-mcp":        "https://foundrynet-mcp-production.up.railway.app/mcp",
    "gov-contracts-mcp":     "https://gov-contracts-mcp-production.up.railway.app/mcp",
    "brand-intel-mcp":       "https://brand-intel-mcp-production.up.railway.app/mcp",
    "patent-intel-mcp":      "https://patent-intel-mcp-production.up.railway.app/mcp",
    "financial-signals-mcp": "https://financial-signals-mcp-production.up.railway.app/mcp",
    "weather-intel-mcp":     "https://weather-intel-mcp-production.up.railway.app/mcp",
    "cyber-intel-mcp":       "https://cyber-intel-mcp-production.up.railway.app/mcp",
    "compliance-mcp":        "https://compliance-mcp-production.up.railway.app/mcp",
    "academic-intel-mcp":    "https://academic-intel-mcp-production.up.railway.app/mcp",
    "fact-check-mcp":        "https://fact-check-mcp-production.up.railway.app/mcp",
    "oss-intel-mcp":         "https://oss-intel-mcp-production.up.railway.app/mcp",
    "social-intel-mcp":      "https://social-intel-mcp-production.up.railway.app/mcp",
    "crypto-intel-mcp":      "https://crypto-intel-mcp-production.up.railway.app/mcp",
    "market-data-mcp":       "https://market-data-mcp-production.up.railway.app/mcp",
    "email-verify-mcp":      "https://email-verify-mcp-production.up.railway.app/mcp",
    "currency-intel-mcp":    "https://currency-intel-mcp-production.up.railway.app/mcp",
}
SISTER_SERVERS = {k: v for k, v in _FNET_ALL_SERVERS.items() if k != "brand-intel-mcp"}

# ── Subscriptions (network-wide $19/$49 Stripe links; same on every server) ──────
# These lead the 402 response: a credit-card subscription converts where "send USDC
# with an SPL-memo" does not. Both unlock unlimited queries here; Intelligence also
# unlocks Knowledge Bases + composite products on foundrynet-agents.
STRIPE_LINK_PRO      = _env("STRIPE_LINK_PRO",   "https://buy.stripe.com/3cIdR278Cglq7bY5b67N604")
STRIPE_LINK_INTEL    = _env("STRIPE_LINK_INTEL", "https://buy.stripe.com/4gMaEQ78C8SYaoa32Y7N605")
NETWORK_SERVER_COUNT = int(_env("NETWORK_SERVER_COUNT", "17"))

# ── Dynamic allowlist (subscriber keys, 5-min cache; static env = fallback) ──────
# Default: poll the agents /v1/allowlist (no DB creds needed). To read forge_api_keys
# directly instead, set FORGE_KEYS_SUPABASE_URL + FORGE_KEYS_SUPABASE_KEY.
FNET_ALLOWLIST_URL      = _env("FNET_ALLOWLIST_URL",
                               "https://foundrynet-agents-production.up.railway.app/v1/allowlist")
FORGE_KEYS_SUPABASE_URL = _env("FORGE_KEYS_SUPABASE_URL", "")
FORGE_KEYS_SUPABASE_KEY = _env("FORGE_KEYS_SUPABASE_KEY", "")

# ── Per-call event log (fire-and-forget telemetry to the agents ingest) ──────────
EVENT_LOG_URL   = _env("EVENT_LOG_URL",
                       "https://foundrynet-agents-production.up.railway.app/v1/call-events")
EVENT_LOG_TOKEN = _env("EVENT_LOG_TOKEN", "")
