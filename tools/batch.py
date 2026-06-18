from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def batch_enrich(
        domains: list,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Enrich many domains at once and get back an array of full brand-intel
        profiles — the volume play for sales / lead-enrichment agents. Up to 50
        domains per call, served from cache where fresh.

        PAID: $0.01 USDC per domain, minimum $0.05, after the daily free allowance.
        The exact price is computed from the (deduped) domain count and returned in
        the 402; pay that memo and re-call with the SAME domains plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            domains: array of domains, e.g. ["stripe.com", "plaid.com"].
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_batch(
            domains, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
