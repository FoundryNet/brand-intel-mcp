# Brand Intelligence MCP

**Domain & brand intelligence for AI agents** — company enrichment, domain
intelligence, tech stack detection, and brand research from free public sources,
with an on-demand cache.

## Connect

- **MCP endpoint** (Streamable HTTP): `https://brand-intel-mcp-production.up.railway.app/mcp`
- **Registry:** `io.github.FoundryNet/brand-intel-mcp`
- **Agent card:** `https://brand-intel-mcp-production.up.railway.app/.well-known/agent-card.json`

### Claude Desktop / Cursor / Claude Code

```
claude mcp add --transport http brand-intel https://brand-intel-mcp-production.up.railway.app/mcp
```

```json
{ "mcpServers": { "brand-intel": { "url": "https://brand-intel-mcp-production.up.railway.app/mcp" } } }
```

## Tools

| Tool | Price | What it does |
|---|---|---|
| `domain_profile` | $0.02 | Full profile: registrar, dates, nameservers, SSL (CT logs), tech stack, CMS, hosting, Wayback history, socials |
| `tech_stack` | $0.01 | Detected technologies, CMS, hosting provider |
| `domain_age` | **free** | Registration date, age in days, expiry |
| `batch_enrich` | $0.01/domain (min $0.05) | Array of profiles — the volume play for sales agents (≤50 domains) |

**Free tier:** 10 paid-tool queries/day per agent (plus unlimited free
`domain_age`). Pass `agent_id` to scope your allowance. After that, x402: the tool
returns an HTTP-402 with a payment memo (price varies by tool/batch size) — send
the USDC on Solana with that memo, then re-call with the same args plus
`payment_tx=<signature>`. An `Authorization: Bearer fnet_…` key bypasses the paywall.

## How it works

On a query for a domain that's **missing or stale (>7 days)**, the server enriches
live and caches the result in its own standalone Supabase project; otherwise it
returns the cache. A daily background task refreshes stale rows.

Sources (all free): **WHOIS** (python-whois), **DNS** (dnspython), **SSL/CT logs**
(crt.sh), **Wayback Machine** (CDX API), **tech fingerprinting** (homepage +
headers, IP→org for hosting), and **socials** (GitHub verified via API;
Twitter/LinkedIn candidate URLs).

**Honesty notes:** GitHub presence is API-verified; Twitter/LinkedIn are candidate
URLs (leads, not confirmations). `employee_estimate` has no reliable free source,
so it's left null rather than fabricated — a future paid-enrichment hook.

Smithery: `io.github.FoundryNet/brand-intel-mcp`

Built by [FoundryNet](https://foundrynet.io) · hello@foundrynet.io

## Live network activity

**Live feed:** [mint.foundrynet.io/feed](https://mint.foundrynet.io/feed)  
Real-time verified work across 13 servers and autonomous agents, anchored on Solana via [MINT Protocol](https://mint.foundrynet.io).
