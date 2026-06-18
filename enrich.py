"""Domain enrichment — gathers brand intelligence from free sources.

All functions are synchronous and defensive (return None / [] on any failure) so
one flaky source never sinks the whole profile. The async server calls
`enrich_domain` via asyncio.to_thread.

Sources (all free):
  • WHOIS         python-whois (registrar, dates, nameservers)
  • DNS           dnspython (NS, A records)
  • CT logs       crt.sh JSON API (SSL issuer + expiry)
  • Wayback       web.archive.org CDX API (first snapshot + total count)
  • Tech stack    homepage HTML + response headers heuristics; IP→org for hosting
  • Socials       GitHub API (verified); Twitter/LinkedIn candidate URLs (best-effort)

Honesty: GitHub presence is verified via the API. Twitter/LinkedIn are CANDIDATE
URLs derived from the brand handle and probed best-effort — treat as leads, not
confirmations. employee_estimate has no reliable free source, so it stays null
(a future paid-enrichment hook) rather than being fabricated.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("brand.enrich")

_UA = {"User-Agent": "brand-intel-mcp/1.0 (+https://foundrynet.io)"}
_HTTP_TIMEOUT = 12


def _norm_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    return d[4:] if d.startswith("www.") else d


def _brand_handle(domain: str) -> str:
    """'stripe' from 'stripe.com' / 'shop.stripe.co.uk' — the registrable label."""
    parts = _norm_domain(domain).split(".")
    return parts[0] if parts else domain


def _iso(dt) -> Optional[str]:
    if isinstance(dt, list):
        dt = dt[0] if dt else None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(dt, str) and dt.strip():
        return dt.strip()
    return None


# ── WHOIS ─────────────────────────────────────────────────────────────────────
def fetch_whois(domain: str) -> dict:
    out = {"registrar": None, "registration_date": None, "expiry_date": None,
           "nameservers": None}
    try:
        import whois  # python-whois
        w = whois.whois(domain)
        out["registrar"] = (w.registrar if isinstance(w.registrar, str)
                            else (w.registrar[0] if w.registrar else None))
        out["registration_date"] = _iso(w.creation_date)
        out["expiry_date"] = _iso(w.expiration_date)
        ns = w.name_servers
        if ns:
            if isinstance(ns, str):
                ns = [ns]
            out["nameservers"] = sorted({n.strip().lower() for n in ns if n})
    except Exception as e:  # noqa: BLE001
        logger.info(f"whois({domain}) failed: {e}")
    return out


# ── DNS ───────────────────────────────────────────────────────────────────────
def fetch_dns(domain: str) -> dict:
    out = {"nameservers": None, "ip": None}
    try:
        import dns.resolver
        try:
            ns = dns.resolver.resolve(domain, "NS", lifetime=8)
            out["nameservers"] = sorted({r.to_text().rstrip(".").lower() for r in ns})
        except Exception:  # noqa: BLE001
            pass
        try:
            a = dns.resolver.resolve(domain, "A", lifetime=8)
            out["ip"] = a[0].to_text() if len(a) else None
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        logger.info(f"dns({domain}) failed: {e}")
    return out


# ── SSL (live cert via direct TLS; CT logs via crt.sh as a best-effort extra) ──
def fetch_ssl(domain: str) -> dict:
    """Live leaf cert issuer + expiry via a direct TLS handshake — fast and
    reliable (crt.sh is frequently slow/unreachable, so it's only a fallback)."""
    out = {"ssl_issuer": None, "ssl_expiry": None}
    try:
        import socket
        import ssl
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ss:
                cert = ss.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", []))
        out["ssl_issuer"] = issuer.get("organizationName") or issuer.get("commonName")
        na = cert.get("notAfter")
        if na:
            dt = datetime.strptime(na, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            out["ssl_expiry"] = dt.isoformat()
    except Exception as e:  # noqa: BLE001
        logger.info(f"tls({domain}) failed: {e}")
    return out


# ── Wayback Machine ───────────────────────────────────────────────────────────
def fetch_wayback(domain: str) -> dict:
    """First snapshot via a cheap CDX limit=1 (CDX returns chronological order);
    total distinct days via a best-effort collapse query. Each is independent so a
    slow/total failure still leaves the first snapshot populated."""
    out = {"wayback_first_snapshot": None, "wayback_total_snapshots": None}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_UA) as c:
            r = c.get("https://web.archive.org/cdx/search/cdx",
                      params={"url": domain, "output": "json", "fl": "timestamp", "limit": "1"})
            if r.status_code == 200:
                rows = r.json()
                if len(rows) > 1:
                    first = rows[1][0]
                    out["wayback_first_snapshot"] = f"{first[0:4]}-{first[4:6]}-{first[6:8]}"
            try:
                r2 = c.get("https://web.archive.org/cdx/search/cdx",
                           params={"url": domain, "output": "json", "fl": "timestamp",
                                   "collapse": "timestamp:8", "limit": "50000"})
                if r2.status_code == 200:
                    rows2 = r2.json()
                    if len(rows2) > 1:
                        out["wayback_total_snapshots"] = len(rows2) - 1
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        logger.info(f"wayback({domain}) failed: {e}")
    return out


# ── Tech stack / CMS / hosting (homepage heuristics + IP org) ─────────────────
_TECH_SIGNATURES = [
    # (needle, technology, optional cms)
    ("wp-content", "WordPress", "WordPress"),
    ("wp-includes", "WordPress", "WordPress"),
    ("cdn.shopify.com", "Shopify", "Shopify"),
    ("x-shopify", "Shopify", "Shopify"),
    ("static.wixstatic.com", "Wix", "Wix"),
    ("squarespace", "Squarespace", "Squarespace"),
    ("assets.webflow.com", "Webflow", "Webflow"),
    ("drupal", "Drupal", "Drupal"),
    ("joomla", "Joomla", "Joomla"),
    ("ghost", "Ghost", "Ghost"),
    ("__next_data__", "Next.js", None),
    ("/_nuxt/", "Nuxt.js", None),
    ("data-reactroot", "React", None),
    ("react", "React", None),
    ("ng-version", "Angular", None),
    ("vue", "Vue.js", None),
    ("gatsby", "Gatsby", None),
    ("hubspot", "HubSpot", None),
    ("google-analytics.com", "Google Analytics", None),
    ("googletagmanager", "Google Tag Manager", None),
    ("cdn.segment.com", "Segment", None),
    ("intercom", "Intercom", None),
    ("stripe.com/v3", "Stripe", None),
    ("cloudflareinsights", "Cloudflare", None),
]

_HEADER_HOSTING = [
    ("cf-ray", "Cloudflare"),
    ("x-vercel-id", "Vercel"),
    ("x-nf-request-id", "Netlify"),
    ("x-served-by", "Fastly"),
    ("x-amz-cf-id", "AWS CloudFront"),
    ("x-github-request-id", "GitHub Pages"),
]


def fetch_tech(domain: str, ip: Optional[str] = None) -> dict:
    out = {"tech_stack": [], "cms": None, "hosting_provider": None,
           "industry_estimate": None}
    techs: set = set()
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_UA, follow_redirects=True) as c:
            r = c.get(f"https://{domain}")
        html = (r.text or "")[:200000].lower()
        headers = {k.lower(): v for k, v in r.headers.items()}

        for needle, tech, cms in _TECH_SIGNATURES:
            if needle in html or any(needle in v.lower() for v in headers.values()):
                techs.add(tech)
                if cms and not out["cms"]:
                    out["cms"] = cms

        # meta generator → CMS
        m = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html)
        if m:
            gen = m.group(1).strip()
            if gen and not out["cms"]:
                out["cms"] = gen.split()[0]
            techs.add(gen.split()[0])

        # Server / x-powered-by headers
        srv = headers.get("server")
        if srv:
            for s in ("nginx", "apache", "cloudflare", "openresty", "litespeed", "iis"):
                if s in srv.lower():
                    techs.add(s.capitalize() if s != "iis" else "IIS")
        xp = headers.get("x-powered-by")
        if xp:
            techs.add(xp.split("/")[0].strip())

        # hosting from headers
        for hk, prov in _HEADER_HOSTING:
            if hk in headers:
                out["hosting_provider"] = prov
                techs.add(prov)
                break

        # industry estimate: crude keyword scan of title + meta description
        title = ""
        mt = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
        if mt:
            title = mt.group(1)
        md = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html)
        desc = md.group(1) if md else ""
        out["industry_estimate"] = _guess_industry(f"{title} {desc}")
    except Exception as e:  # noqa: BLE001
        logger.info(f"tech({domain}) failed: {e}")

    # hosting fallback: IP → org via ip-api.com (free, no key)
    if not out["hosting_provider"] and ip:
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_UA) as c:
                r = c.get(f"http://ip-api.com/json/{ip}",
                          params={"fields": "status,org,isp,as"})
            if r.status_code == 200:
                j = r.json()
                if j.get("status") == "success":
                    out["hosting_provider"] = j.get("org") or j.get("isp") or j.get("as")
        except Exception:  # noqa: BLE001
            pass

    out["tech_stack"] = sorted(t for t in techs if t)
    return out


_INDUSTRY_KEYWORDS = {
    "E-commerce / Retail": ["shop", "store", "cart", "checkout", "buy now", "ecommerce"],
    "SaaS / Software": ["platform", "api", "software", "saas", "dashboard", "integrations"],
    "Finance / Fintech": ["bank", "payment", "invoice", "lending", "fintech", "crypto", "trading"],
    "Healthcare": ["health", "clinic", "patient", "medical", "pharma", "therapy"],
    "Education": ["course", "learn", "student", "education", "university", "training"],
    "Media / Content": ["news", "blog", "magazine", "podcast", "media"],
    "Real Estate": ["property", "real estate", "rent", "listing", "mortgage"],
    "Manufacturing / Industrial": ["manufacturing", "industrial", "factory", "machinery", "equipment"],
}


def _guess_industry(text: str) -> Optional[str]:
    t = (text or "").lower()
    best, score = None, 0
    for industry, kws in _INDUSTRY_KEYWORDS.items():
        s = sum(1 for k in kws if k in t)
        if s > score:
            best, score = industry, s
    return best if score else None


# ── Socials ───────────────────────────────────────────────────────────────────
def fetch_socials(domain: str) -> dict:
    out = {"social_twitter": None, "social_linkedin": None, "social_github": None}
    handle = _brand_handle(domain)
    if not handle:
        return out
    # GitHub — verified via API (user or org).
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_UA) as c:
            for kind in ("users", "orgs"):
                r = c.get(f"https://api.github.com/{kind}/{handle}")
                if r.status_code == 200:
                    out["social_github"] = f"https://github.com/{handle}"
                    break
    except Exception:  # noqa: BLE001
        pass
    # Twitter/X + LinkedIn — candidate URLs (best-effort, not strongly verified).
    out["social_twitter"] = f"https://x.com/{handle}"
    out["social_linkedin"] = f"https://www.linkedin.com/company/{handle}"
    return out


# ── orchestration ─────────────────────────────────────────────────────────────
def enrich_domain(domain: str, *, full: bool = True) -> dict:
    """Build a brand_intel row for `domain`. full=False does WHOIS+DNS only (the
    cheap domain_age path); full=True adds SSL/Wayback/tech/socials."""
    d = _norm_domain(domain)
    row: dict = {"domain": d}
    w = fetch_whois(d)
    dns_ = fetch_dns(d)
    row["registrar"] = w["registrar"]
    row["registration_date"] = w["registration_date"]
    row["expiry_date"] = w["expiry_date"]
    row["nameservers"] = dns_["nameservers"] or w["nameservers"]

    if full:
        row.update({k: v for k, v in fetch_ssl(d).items()})
        row.update({k: v for k, v in fetch_wayback(d).items()})
        tech = fetch_tech(d, ip=dns_.get("ip"))
        row["tech_stack"] = tech["tech_stack"]
        row["cms"] = tech["cms"]
        row["hosting_provider"] = tech["hosting_provider"]
        row["industry_estimate"] = tech["industry_estimate"]
        row.update({k: v for k, v in fetch_socials(d).items()})
        row["employee_estimate"] = None  # no reliable free source — honest null
        row["enrich_level"] = "full"
    else:
        row["enrich_level"] = "whois"

    row["last_checked"] = datetime.now(timezone.utc).isoformat()
    return row
