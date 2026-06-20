import core


def register(mcp) -> None:
    @mcp.tool
    async def mint_info() -> dict:
        """Get FoundryNet Data Network info and MINT Protocol attestation details. FREE.

        Returns how to attest your agent's domain/brand intelligence with MINT
        Protocol for verifiable on-chain proof, the MINT MCP endpoint, and the
        sister data servers (gov-contracts, patent-intel, financial-signals,
        weather-intel, cyber-intel, compliance, academic-intel, fact-check,
        oss-intel, social-intel).
        """
        return core.mint_info()
