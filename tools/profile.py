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
        """Profile a company or domain for company enrichment and lead enrichment:
        registration age and registrar (WHOIS/RDAP), nameservers, SSL issuer +
        expiry (SSL/CT logs), tech stack detection (CMS, frameworks, hosting),
        Wayback history, and social profiles. Domain intelligence and company
        research in one call — automatically enriched with cross-server intelligence
        from the FoundryNet Data Network (financial signals, patents, regulatory/
        compliance actions, open-source risk, and domain threat reputation) when
        available, returned under `network_intelligence`. Served from a 7-day cache;
        a miss enriches live.

        PAID: $0.05 per query after a daily free allowance (10/day). On a 402,
        settle the returned payment memo and re-call with the SAME args plus
        payment_tx=<signature>. Pass agent_id to scope your free allowance; an
        Authorization: Bearer fnet_ key bypasses the paywall.

        Args:
            domain: the domain to profile, e.g. "stripe.com".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: payment transaction reference, when re-calling after a 402.
        """
        return await core.do_profile(
            domain, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
