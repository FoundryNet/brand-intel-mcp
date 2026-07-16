from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def daily_brief(
        date: Optional[str] = None,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
        stripe_token: Optional[str] = None,
    ) -> dict:
        """Get the curated daily brand & domain intelligence brief — the day's
        company-enrichment activity in one package: an activity summary (domains
        profiled / enriched in 24h), notable findings (recently registered domains
        via WHOIS, interesting tech-stack detection / hosting), and cached domains
        whose SSL certs expire soon (next 30 days). For company research and lead
        enrichment. Each brief carries a cryptographic provenance attestation so a
        buyer can verify it was produced by this server, unaltered.

        PAID: $5 per brief. Defaults to today (UTC); a brief expires at the next
        midnight UTC. On a 402, settle the returned payment memo and re-call with the
        SAME args plus payment_tx=<signature>. An Authorization: Bearer fnet_ key
        bypasses payment.

        Args:
            date: brief date YYYY-MM-DD (default today, UTC).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: payment transaction reference, when re-calling after a 402.
            stripe_token: Stripe Checkout Session id (cs_…), when re-calling after
                paying the Stripe payment link (alternative payment rail). Can also be
                supplied via the X-Stripe-Token header.
        """
        return await core.do_daily_brief(
            date, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer(),
            stripe_token=stripe_token or identity.stripe_token())
