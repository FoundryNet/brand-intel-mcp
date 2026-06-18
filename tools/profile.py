from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def domain_profile(
        domain: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Full brand-intelligence profile for a domain: registrar + registration /
        expiry dates, nameservers, SSL issuer + expiry (from CT logs), detected
        tech stack + CMS + hosting provider, Wayback history (first snapshot + total
        snapshots), and social profiles. Great for company enrichment and brand
        research. Served from a 7-day cache; a miss enriches live.

        PAID: $0.02 USDC per query after a daily free allowance (10/day). On a 402,
        pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. Pass agent_id to scope your free allowance; an
        Authorization: Bearer fnet_ key bypasses the paywall.

        Args:
            domain: the domain to profile, e.g. "stripe.com".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_profile(
            domain, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
