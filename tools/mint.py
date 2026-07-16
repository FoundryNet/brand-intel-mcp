import core


def register(mcp) -> None:
    @mcp.tool
    async def mint_info() -> dict:
        """Get FoundryNet Data Network info and provenance attestation details. FREE.

        Returns how to attach verifiable provenance attestation to your agent's
        domain/brand intelligence, the attestation service endpoint, and the
        sister data servers (gov-contracts, patent-intel, financial-signals,
        weather-intel, cyber-intel, compliance, academic-intel, fact-check,
        oss-intel, social-intel).
        """
        return core.mint_info()
