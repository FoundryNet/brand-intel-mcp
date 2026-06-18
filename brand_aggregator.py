#!/usr/bin/env python3
"""brand_aggregator — daily refresh / seeding for the brand_intel cache.

The brand-intel-mcp server enriches on-demand (cache miss/stale) and runs this same
refresh as an in-process daily task, so this script is for: (a) a separate cron if
you prefer one, and (b) manual seeding of specific domains.

Usage:
  python brand_aggregator.py                 # refresh stale (>TTL) cached domains
  python brand_aggregator.py stripe.com x.ai # force-enrich specific domains
"""
from __future__ import annotations

import asyncio
import sys

import core
import enrich
import supa


async def _seed(domains: list[str]) -> None:
    for d in domains:
        dn = enrich._norm_domain(d)
        row = await asyncio.to_thread(enrich.enrich_domain, dn, full=True)
        res = await supa.upsert_domain(row)
        ok = "error" not in res
        print(f"{'✓' if ok else '✗'} {dn} "
              f"(cms={row.get('cms')}, tech={len(row.get('tech_stack') or [])}, "
              f"reg={row.get('registration_date')})")


async def main() -> None:
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        await _seed(args)
    else:
        n = await core.refresh_stale(limit=500)
        print(f"refreshed {n} stale domains")


if __name__ == "__main__":
    asyncio.run(main())
