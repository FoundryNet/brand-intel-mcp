from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def tech_stack(
        domain: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Analyze a domain's tech stack — frameworks, CMS, hosting provider,
        analytics, and platform signals — via tech-stack detection over homepage
        and HTTP response-header fingerprinting. Domain intelligence for company
        research, competitive analysis, and lead enrichment.

        PAID: $0.01 USDC per query after the daily free allowance (10/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            domain: the domain to inspect, e.g. "shopify.com".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_tech(
            domain, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
