"""brand-intel-mcp tools — one per file.

  domain_profile   — full brand intelligence profile        ($0.02)
  tech_stack       — detected technologies / CMS / hosting   ($0.01)
  domain_age       — registration date, age, expiry          (free)
  batch_enrich     — array of profiles (the volume play)     ($0.01/domain, min $0.05)
  daily_brief      — curated daily cache/SSL brief            ($5)
"""
from . import profile as profile_tool
from . import tech as tech_tool
from . import age as age_tool
from . import batch as batch_tool
from . import daily_brief as daily_brief_tool
from . import mint as mint_tool


def register_all(mcp) -> None:
    profile_tool.register(mcp)
    tech_tool.register(mcp)
    age_tool.register(mcp)
    batch_tool.register(mcp)
    daily_brief_tool.register(mcp)
    mint_tool.register(mcp)
