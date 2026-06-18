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
  FREE_TIER_DAILY         free paid-tool queries/day per agent, default 10
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

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

CACHE_TTL_DAYS  = int(_env("CACHE_TTL_DAYS", "7"))
REFRESH_INTERVAL_HOURS = int(_env("REFRESH_INTERVAL_HOURS", "24"))

# ── x402 pay-per-query gate (per-tool pricing) ───────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWWvtFEr69qkTw3wHNVQVxLA8DTyJSyVgGmLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "10"))

PRICE_DOMAIN_PROFILE   = float(_env("PRICE_DOMAIN_PROFILE", "0.02"))
PRICE_TECH_STACK       = float(_env("PRICE_TECH_STACK", "0.01"))
PRICE_BATCH_PER_DOMAIN = float(_env("PRICE_BATCH_PER_DOMAIN", "0.01"))
PRICE_BATCH_MIN        = float(_env("PRICE_BATCH_MIN", "0.05"))

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://brand-intel-mcp-production.up.railway.app/mcp")
