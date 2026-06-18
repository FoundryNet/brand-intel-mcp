import core


def register(mcp) -> None:
    @mcp.tool
    async def domain_age(domain: str) -> dict:
        """Registration date, age in days, and expiry for a domain. FREE — no
        payment and no free-tier consumption. (On a cache miss it does a quick
        WHOIS lookup and caches it.)

        Args:
            domain: the domain to check, e.g. "openai.com".
        """
        return await core.do_age(domain)
