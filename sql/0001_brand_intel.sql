-- Domain & Brand Intelligence — schema for brand_aggregator + brand-intel-mcp.
-- Standalone Supabase project (NOT the core Foundry one). Idempotent.

-- ── brand_intel (the cache) ──────────────────────────────────────────────────
create table if not exists brand_intel (
  domain                   text primary key,
  registrar                text,
  registration_date        timestamptz,
  expiry_date              timestamptz,
  nameservers              jsonb,
  ssl_issuer               text,
  ssl_expiry               timestamptz,
  tech_stack               jsonb,          -- array of detected technologies
  cms                      text,
  hosting_provider         text,
  wayback_first_snapshot   date,
  wayback_total_snapshots  integer,
  social_twitter           text,
  social_linkedin          text,
  social_github            text,
  employee_estimate        text,           -- coarse band when derivable, else null
  industry_estimate        text,
  enrich_level             text default 'full',  -- 'whois' (domain_age path) | 'full'
  last_checked             timestamptz not null default now(),
  created_at               timestamptz not null default now()
);

create index if not exists idx_brand_intel_last_checked on brand_intel (last_checked);

-- ── free-tier counter ────────────────────────────────────────────────────────
create table if not exists brand_query_usage (
  agent_key   text not null,
  day         date not null,
  count       integer not null default 0,
  updated_at  timestamptz not null default now(),
  primary key (agent_key, day)
);

create or replace function brand_claim_free_query(p_agent_key text, p_day date, p_cap integer)
returns jsonb language plpgsql as $$
declare cur integer; ok boolean;
begin
  insert into brand_query_usage (agent_key, day, count, updated_at)
  values (p_agent_key, p_day, 0, now())
  on conflict (agent_key, day) do nothing;
  select count into cur from brand_query_usage
    where agent_key = p_agent_key and day = p_day for update;
  if cur < p_cap then
    update brand_query_usage set count = count + 1, updated_at = now()
      where agent_key = p_agent_key and day = p_day;
    ok := true; cur := cur + 1;
  else ok := false; end if;
  return jsonb_build_object('allowed', ok, 'count', cur, 'cap', p_cap);
end; $$;

-- ── x402 payment ledger (double-spend guard + revenue) ───────────────────────
create table if not exists brand_payments (
  tx_signature  text primary key,
  intent        text,
  agent_key     text,
  tool          text,
  amount_usdc   numeric,
  payer_wallet  text,
  recipient     text,
  status        text,
  block_time    bigint,
  created_at    timestamptz not null default now()
);
