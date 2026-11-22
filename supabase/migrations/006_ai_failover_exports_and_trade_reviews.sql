-- ApexPrime 006: AI routing/failover, manual external analyses, exports,
-- opportunity analytics, market snapshots, trade reviews and 100 USDT paper capital.
-- Execute once after migrations 001-005.

-- AI routing and risk/strategy controls.
alter table public.apex_settings
  add column if not exists ai_provider_strategy text not null default 'auto',
  add column if not exists fixed_ai_provider text not null default 'gemini',
  add column if not exists fixed_ai_model text not null default 'gemini-4-hydrogen',
  add column if not exists openrouter_model text not null default 'openrouter/free',
  add column if not exists groq_health_interval_hours integer not null default 4,
  add column if not exists simulate_exchange_minimum boolean not null default true,
  add column if not exists minimum_notional_usdt numeric(20,8) not null default 100,
  add column if not exists trigger_volume_multiplier numeric(6,3) not null default 1.5,
  add column if not exists trigger_sweep_length integer not null default 16,
  add column if not exists trigger_displacement_multiplier numeric(6,3) not null default 1.5,
  add column if not exists trigger_cooldown integer not null default 3,
  add column if not exists trigger_min_score integer not null default 2;

alter table public.apex_settings
  drop constraint if exists apex_settings_ai_provider_strategy_check,
  add constraint apex_settings_ai_provider_strategy_check check (ai_provider_strategy in ('auto','fixed')),
  drop constraint if exists apex_settings_fixed_ai_provider_check,
  add constraint apex_settings_fixed_ai_provider_check check (fixed_ai_provider in ('gemini','openrouter','groq')),
  drop constraint if exists apex_settings_groq_health_interval_hours_check,
  add constraint apex_settings_groq_health_interval_hours_check check (groq_health_interval_hours between 1 and 48),
  drop constraint if exists apex_settings_trigger_volume_multiplier_check,
  add constraint apex_settings_trigger_volume_multiplier_check check (trigger_volume_multiplier between 1 and 5),
  drop constraint if exists apex_settings_trigger_sweep_length_check,
  add constraint apex_settings_trigger_sweep_length_check check (trigger_sweep_length between 2 and 100),
  drop constraint if exists apex_settings_trigger_displacement_multiplier_check,
  add constraint apex_settings_trigger_displacement_multiplier_check check (trigger_displacement_multiplier between 1 and 5),
  drop constraint if exists apex_settings_trigger_cooldown_check,
  add constraint apex_settings_trigger_cooldown_check check (trigger_cooldown between 1 and 30),
  drop constraint if exists apex_settings_trigger_min_score_check,
  add constraint apex_settings_trigger_min_score_check check (trigger_min_score between 1 and 3),
  drop constraint if exists apex_settings_minimum_notional_usdt_check,
  add constraint apex_settings_minimum_notional_usdt_check check (minimum_notional_usdt > 0);

update public.apex_settings
set initial_balance = 100
where id = 1 and initial_balance < 100;

-- Raise an untouched legacy 20-USDT paper account to 100 USDT while preserving
-- any trading gains/losses already made. The +80 is auditable in the ledger.
do $$
declare
  acc record;
begin
  for acc in
    select id, balance, initial_balance
    from public.paper_accounts
    where is_active = true and initial_balance = 20
  loop
    update public.paper_accounts
      set balance = balance + 80,
          initial_balance = 100,
          updated_at = now()
      where id = acc.id;
    insert into public.balance_ledger(account_id, trade_id, event_type, amount, balance_after, description, metadata)
    values (acc.id, null, 'MANUAL_ADJUSTMENT', 80, acc.balance + 80,
            'Atualização do capital virtual ApexPrime de 20 para 100 USDT',
            jsonb_build_object('migration', '006', 'reason', 'paper_capital_upgrade'));
  end loop;
end $$;

-- AI attribution and external analysis support.
alter table public.system_runs
  drop constraint if exists system_runs_source_check;
alter table public.system_runs
  add constraint system_runs_source_check check (source in ('hourly_scan','manual','manual_external','watchdog','test'));
alter table public.system_runs
  add column if not exists analysis_provider text,
  add column if not exists analysis_model text,
  add column if not exists chart_source_type text,
  add column if not exists analysis_source text not null default 'automatic';

alter table public.trades
  add column if not exists analysis_provider text not null default 'GEMINI',
  add column if not exists analysis_model text,
  add column if not exists analysis_mode text,
  add column if not exists analysis_source text not null default 'automatic',
  add column if not exists result_category text,
  add column if not exists analysis_raw_response text,
  add column if not exists entry_text_snapshot text,
  add column if not exists chart_images jsonb not null default '[]'::jsonb,
  add column if not exists post_trade_review_status text not null default 'PENDING';
alter table public.trades
  drop constraint if exists trades_result_category_check,
  add constraint trades_result_category_check check (result_category is null or result_category in ('FULL_WIN','PARTIAL_WIN','LOSS','BREAKEVEN')),
  drop constraint if exists trades_post_trade_review_status_check,
  add constraint trades_post_trade_review_status_check check (post_trade_review_status in ('PENDING','PROCESSING','COMPLETED','ERROR','SKIPPED'));

alter table public.pending_entries
  add column if not exists analysis_provider text not null default 'GEMINI',
  add column if not exists analysis_model text,
  add column if not exists analysis_mode text,
  add column if not exists analysis_source text not null default 'automatic',
  add column if not exists analysis_raw_response text,
  add column if not exists entry_text_snapshot text,
  add column if not exists chart_images jsonb not null default '[]'::jsonb;

create table if not exists public.ai_requests (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.system_runs(id) on delete set null,
  provider text not null check (provider in ('GEMINI','OPENROUTER','GROQ','EXTERNAL')),
  model text not null,
  analysis_mode text not null check (analysis_mode in ('chart_img','text')),
  success boolean not null default false,
  latency_ms integer,
  input_tokens integer,
  output_tokens integer,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists ai_requests_created_idx on public.ai_requests(created_at desc);
create index if not exists ai_requests_provider_idx on public.ai_requests(provider, created_at desc);

-- One compact row per closed trade, with the AI's original analysis and chart-text
-- context captured from entry to exit for Groq's post-trade explanation.
create table if not exists public.trade_reviews (
  id uuid primary key default gen_random_uuid(),
  trade_id uuid not null unique references public.trades(id) on delete cascade,
  analysis_provider text,
  analysis_model text,
  analysis_raw_response text,
  entry_text_snapshot text,
  exit_text_snapshot text,
  groq_review text,
  result_category text,
  realized_pnl_net numeric(20,8),
  review_status text not null default 'PENDING' check (review_status in ('PENDING','PROCESSING','COMPLETED','ERROR')),
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.apex_exports (
  id uuid primary key default gen_random_uuid(),
  export_type text not null check (export_type in ('TEXT_CHART','CHART_IMAGES')),
  status text not null default 'COMPLETED' check (status in ('QUEUED','PROCESSING','COMPLETED','FAILED')),
  symbol text not null default 'BTCUSDT',
  reference_at timestamptz,
  content_text text,
  files jsonb not null default '[]'::jsonb,
  error_message text,
  created_at timestamptz not null default now()
);
create index if not exists apex_exports_created_idx on public.apex_exports(created_at desc);

create table if not exists public.opportunity_events (
  id uuid primary key default gen_random_uuid(),
  symbol text not null default 'BTCUSDT',
  candle_open_time timestamptz not null,
  direction text not null check (direction in ('LONG','SHORT','NONE')),
  score integer not null default 0 check (score between 0 and 3),
  bullish_score integer not null default 0,
  bearish_score integer not null default 0,
  volume_explosion boolean not null default false,
  bull_sweep boolean not null default false,
  bear_sweep boolean not null default false,
  bull_displacement boolean not null default false,
  bear_displacement boolean not null default false,
  reason text,
  settings_snapshot jsonb not null default '{}'::jsonb,
  run_id uuid references public.system_runs(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(symbol, candle_open_time)
);
create index if not exists opportunity_events_created_idx on public.opportunity_events(created_at desc);

create table if not exists public.market_snapshots (
  symbol text primary key,
  mark_price numeric(20,8),
  candles jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.groq_reports (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'PENDING' check (status in ('PENDING','PROCESSING','COMPLETED','ERROR')),
  report_text text,
  snapshot jsonb not null default '{}'::jsonb,
  error_message text,
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists groq_reports_requested_idx on public.groq_reports(requested_at desc);

-- Additional command types used by the PWA. All are worker-side actions.
alter table public.run_requests drop constraint if exists run_requests_request_type_check;
alter table public.run_requests add constraint run_requests_request_type_check check (request_type in (
  'force_analysis','close_open_trade','close_trade','cancel_pending_entry','run_tests',
  'manual_external_analysis','export_text','export_chart_images','add_virtual_balance','groq_report'
));

-- Admin read policies for new records; only the service-role Redmi worker writes to them.
do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='ai_requests' and policyname='ai_requests_admin_read') then
    create policy ai_requests_admin_read on public.ai_requests for select to authenticated using (public.is_apex_admin());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='trade_reviews' and policyname='trade_reviews_admin_read') then
    create policy trade_reviews_admin_read on public.trade_reviews for select to authenticated using (public.is_apex_admin());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='apex_exports' and policyname='apex_exports_admin_read') then
    create policy apex_exports_admin_read on public.apex_exports for select to authenticated using (public.is_apex_admin());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='opportunity_events' and policyname='opportunity_events_admin_read') then
    create policy opportunity_events_admin_read on public.opportunity_events for select to authenticated using (public.is_apex_admin());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='market_snapshots' and policyname='market_snapshots_admin_read') then
    create policy market_snapshots_admin_read on public.market_snapshots for select to authenticated using (public.is_apex_admin());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='groq_reports' and policyname='groq_reports_admin_read') then
    create policy groq_reports_admin_read on public.groq_reports for select to authenticated using (public.is_apex_admin());
  end if;
end $$;

comment on table public.ai_requests is 'All AI providers and fallback attempts, not only Gemini.';
comment on table public.trade_reviews is 'Post-trade Groq review with original analysis and market-text context.';
comment on table public.opportunity_events is 'Every hourly strategy evaluation, including no-signal candles.';
comment on column public.apex_settings.simulate_exchange_minimum is 'Simulate Binance Futures lot/min-notional filters in paper trading; if this would exceed the configured risk limit the entry is blocked.';
