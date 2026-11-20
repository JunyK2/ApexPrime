-- ApexPrime | Supabase initial schema | paper trading only
-- Execute once in Supabase SQL Editor. Never expose service_role keys to the browser.

create extension if not exists pgcrypto;

-- -----------------------------
-- Helpers
-- -----------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.apex_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create or replace function public.is_apex_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.apex_admins a
    where a.user_id = auth.uid()
  );
$$;

revoke all on function public.is_apex_admin() from public;
grant execute on function public.is_apex_admin() to authenticated;

-- -----------------------------
-- Global configuration (single row id=1)
-- -----------------------------
create table if not exists public.apex_settings (
  id smallint primary key default 1 check (id = 1),
  analysis_mode text not null default 'chart_img' check (analysis_mode in ('chart_img','text')),
  avoid_weekends boolean not null default false,
  groq_enabled boolean not null default true,
  groq_alerts_enabled boolean not null default true,
  initial_balance numeric(20,8) not null default 20 check (initial_balance > 0),
  risk_per_trade_pct numeric(6,3) not null default 2.000 check (risk_per_trade_pct > 0 and risk_per_trade_pct <= 2.000),
  max_leverage integer not null default 20 check (max_leverage between 1 and 20),
  max_open_trades integer not null default 1 check (max_open_trades between 1 and 5),
  maker_fee_rate numeric(12,8) not null default 0.00020000 check (maker_fee_rate >= 0 and maker_fee_rate < 0.02),
  taker_fee_rate numeric(12,8) not null default 0.00050000 check (taker_fee_rate >= 0 and taker_fee_rate < 0.02),
  funding_enabled boolean not null default true,
  gemini_model text not null default 'gemini-4-hydrogen',
  groq_model text not null default 'openai/gpt-oss-120b',
  binance_symbol text not null default 'BTCUSDT',
  timezone text not null default 'America/Sao_Paulo',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.apex_prompts (
  id smallint primary key default 1 check (id = 1),
  custom_chart_img_prompt text,
  custom_text_prompt text,
  updated_at timestamptz not null default now()
);

-- -----------------------------
-- Virtual account + audit ledger
-- -----------------------------
create table if not exists public.paper_accounts (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'ApexPrime Paper Account',
  initial_balance numeric(20,8) not null default 20 check (initial_balance > 0),
  balance numeric(20,8) not null default 20,
  realized_pnl numeric(20,8) not null default 0,
  total_fees numeric(20,8) not null default 0,
  total_funding numeric(20,8) not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists paper_accounts_one_active_idx
  on public.paper_accounts (is_active) where is_active = true;

create table if not exists public.balance_ledger (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.paper_accounts(id) on delete restrict,
  trade_id uuid,
  event_type text not null check (event_type in ('INITIAL_BALANCE','REALIZED_PNL','FEE','FUNDING','MANUAL_ADJUSTMENT','RESET')),
  amount numeric(20,8) not null,
  balance_after numeric(20,8) not null,
  description text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- -----------------------------
-- Runs, analysis and model usage
-- -----------------------------
create table if not exists public.system_runs (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('hourly_scan','manual','watchdog','test')),
  status text not null default 'queued' check (status in ('queued','running','completed','skipped','failed')),
  analysis_mode text check (analysis_mode in ('chart_img','text')),
  symbol text not null default 'BTCUSDT',
  trigger_time timestamptz,
  trigger_candle_open_time timestamptz,
  trigger_direction text check (trigger_direction in ('LONG','SHORT','NONE')),
  trigger_score integer check (trigger_score between 0 and 3),
  signal text check (signal in ('LONG','SHORT','NO_TRADE')),
  ai_model text,
  market_snapshot jsonb not null default '{}'::jsonb,
  chart_images jsonb not null default '[]'::jsonb,
  apex_table jsonb,
  ai_raw_response text,
  error_code text,
  error_message text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  created_at timestamptz not null default now()
);
create index if not exists system_runs_created_at_idx on public.system_runs (created_at desc);
create unique index if not exists system_runs_hourly_candle_unique
  on public.system_runs (symbol, trigger_candle_open_time)
  where source = 'hourly_scan' and trigger_candle_open_time is not null;

create table if not exists public.gemini_requests (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.system_runs(id) on delete set null,
  model text not null,
  analysis_mode text not null check (analysis_mode in ('chart_img','text')),
  success boolean not null default false,
  prompt_chars integer,
  input_tokens integer,
  output_tokens integer,
  total_tokens integer,
  latency_ms integer,
  error_code text,
  error_message text,
  created_at timestamptz not null default now()
);
create index if not exists gemini_requests_created_at_idx on public.gemini_requests (created_at desc);

-- -----------------------------
-- Simulated trades and lifecycle events
-- -----------------------------
create table if not exists public.trades (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.paper_accounts(id) on delete restrict,
  run_id uuid references public.system_runs(id) on delete set null,
  symbol text not null default 'BTCUSDT',
  direction text not null check (direction in ('LONG','SHORT')),
  entry_type text not null check (entry_type in ('IMEDIATA','PULLBACK','CONFIRMACAO')),
  status text not null default 'OPEN' check (status in ('OPEN','CLOSED')),
  entry_price numeric(20,8) not null check (entry_price > 0),
  initial_stop_loss numeric(20,8) not null check (initial_stop_loss > 0),
  current_stop_loss numeric(20,8) not null check (current_stop_loss > 0),
  tp1_price numeric(20,8) not null check (tp1_price > 0),
  tp2_price numeric(20,8) not null check (tp2_price > 0),
  initial_quantity numeric(28,12) not null check (initial_quantity > 0),
  remaining_quantity numeric(28,12) not null check (remaining_quantity >= 0),
  leverage integer not null check (leverage between 1 and 20),
  notional numeric(20,8) not null check (notional > 0),
  margin_used numeric(20,8) not null check (margin_used >= 0),
  risk_amount numeric(20,8) not null check (risk_amount >= 0),
  risk_pct numeric(8,4) not null check (risk_pct >= 0 and risk_pct <= 2.0000),
  tp1_fraction numeric(6,5) not null default 0.50000 check (tp1_fraction > 0 and tp1_fraction < 1),
  tp1_hit boolean not null default false,
  break_even_moved boolean not null default false,
  confidence text check (confidence in ('BAIXA','MEDIA','ALTA')),
  score numeric(5,2) check (score is null or score between 0 and 10),
  regime text check (regime in ('TENDENCIA','RANGE','TRANSICAO')),
  strategy_name text,
  analysis_summary text,
  entry_fee numeric(20,8) not null default 0,
  exit_fees numeric(20,8) not null default 0,
  funding_paid numeric(20,8) not null default 0,
  realized_pnl_gross numeric(20,8) not null default 0,
  realized_pnl_net numeric(20,8) not null default 0,
  exit_price numeric(20,8),
  close_reason text check (close_reason in ('TP2','STOP_LOSS','MANUAL','SIGNAL_REVERSAL','RISK_GUARD','CANCELLED')),
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  updated_at timestamptz not null default now(),
  check (direction <> 'LONG' or (initial_stop_loss < entry_price and tp1_price > entry_price and tp2_price > tp1_price)),
  check (direction <> 'SHORT' or (initial_stop_loss > entry_price and tp1_price < entry_price and tp2_price < tp1_price)),
  check ((status = 'OPEN' and closed_at is null and close_reason is null) or (status = 'CLOSED' and closed_at is not null and close_reason is not null))
);
create index if not exists trades_status_opened_idx on public.trades (status, opened_at desc);
create index if not exists trades_account_opened_idx on public.trades (account_id, opened_at desc);

alter table public.balance_ledger
  drop constraint if exists balance_ledger_trade_id_fkey;
alter table public.balance_ledger
  add constraint balance_ledger_trade_id_fkey foreign key (trade_id) references public.trades(id) on delete set null;

create table if not exists public.trade_events (
  id uuid primary key default gen_random_uuid(),
  trade_id uuid not null references public.trades(id) on delete cascade,
  event_type text not null check (event_type in ('OPENED','TP1_PARTIAL','STOP_TO_BREAKEVEN','STOP_UPDATED','STOP_LOSS','TP2_CLOSED','MANUAL_EXIT','FUNDING_CHARGED','FEE_CHARGED','TRADE_CANCELLED','RISK_GUARD_EXIT')),
  price numeric(20,8),
  quantity numeric(28,12),
  realized_pnl_gross numeric(20,8) not null default 0,
  fee numeric(20,8) not null default 0,
  funding numeric(20,8) not null default 0,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists trade_events_trade_created_idx on public.trade_events (trade_id, created_at);

-- -----------------------------
-- Manual requests, logs and health checks
-- -----------------------------
create table if not exists public.run_requests (
  id uuid primary key default gen_random_uuid(),
  requested_by uuid not null references auth.users(id) on delete restrict,
  request_type text not null default 'force_analysis' check (request_type in ('force_analysis','close_open_trade','run_tests')),
  status text not null default 'pending' check (status in ('pending','processing','completed','failed','cancelled')),
  payload jsonb not null default '{}'::jsonb,
  result jsonb,
  run_id uuid references public.system_runs(id) on delete set null,
  error_message text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index if not exists run_requests_pending_idx on public.run_requests (status, requested_at) where status = 'pending';

create table if not exists public.apex_logs (
  id bigint generated always as identity primary key,
  run_id uuid references public.system_runs(id) on delete set null,
  level text not null check (level in ('DEBUG','INFO','WARN','ERROR','CRITICAL')),
  component text not null,
  message text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists apex_logs_created_idx on public.apex_logs (created_at desc);
create index if not exists apex_logs_level_idx on public.apex_logs (level, created_at desc);

create table if not exists public.service_checks (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.system_runs(id) on delete set null,
  service text not null check (service in ('BINANCE','SUPABASE','GEMINI','GROQ','CHART_IMG','TELEGRAM','TEXT_GENERATOR')),
  status text not null check (status in ('OK','WARN','ERROR')),
  latency_ms integer,
  message text,
  details jsonb not null default '{}'::jsonb,
  checked_at timestamptz not null default now()
);
create index if not exists service_checks_checked_idx on public.service_checks (checked_at desc);

-- -----------------------------
-- updated_at triggers
-- -----------------------------
drop trigger if exists apex_settings_updated_at on public.apex_settings;
create trigger apex_settings_updated_at before update on public.apex_settings
for each row execute function public.set_updated_at();
drop trigger if exists apex_prompts_updated_at on public.apex_prompts;
create trigger apex_prompts_updated_at before update on public.apex_prompts
for each row execute function public.set_updated_at();
drop trigger if exists paper_accounts_updated_at on public.paper_accounts;
create trigger paper_accounts_updated_at before update on public.paper_accounts
for each row execute function public.set_updated_at();
drop trigger if exists trades_updated_at on public.trades;
create trigger trades_updated_at before update on public.trades
for each row execute function public.set_updated_at();

-- -----------------------------
-- RLS: deny by default; admin-only dashboard access
-- -----------------------------
alter table public.apex_admins enable row level security;
alter table public.apex_settings enable row level security;
alter table public.apex_prompts enable row level security;
alter table public.paper_accounts enable row level security;
alter table public.balance_ledger enable row level security;
alter table public.system_runs enable row level security;
alter table public.gemini_requests enable row level security;
alter table public.trades enable row level security;
alter table public.trade_events enable row level security;
alter table public.run_requests enable row level security;
alter table public.apex_logs enable row level security;
alter table public.service_checks enable row level security;

-- User can only see their own admin membership. Membership is provisioned via SQL by the project owner.
create policy "admins_read_own_membership" on public.apex_admins
for select to authenticated using (user_id = auth.uid());

create policy "settings_admin_read" on public.apex_settings
for select to authenticated using (public.is_apex_admin());
create policy "settings_admin_update" on public.apex_settings
for update to authenticated using (public.is_apex_admin()) with check (public.is_apex_admin());

create policy "prompts_admin_read" on public.apex_prompts
for select to authenticated using (public.is_apex_admin());
create policy "prompts_admin_update" on public.apex_prompts
for update to authenticated using (public.is_apex_admin()) with check (public.is_apex_admin());

create policy "paper_accounts_admin_read" on public.paper_accounts
for select to authenticated using (public.is_apex_admin());
create policy "balance_ledger_admin_read" on public.balance_ledger
for select to authenticated using (public.is_apex_admin());
create policy "system_runs_admin_read" on public.system_runs
for select to authenticated using (public.is_apex_admin());
create policy "gemini_requests_admin_read" on public.gemini_requests
for select to authenticated using (public.is_apex_admin());
create policy "trades_admin_read" on public.trades
for select to authenticated using (public.is_apex_admin());
create policy "trade_events_admin_read" on public.trade_events
for select to authenticated using (public.is_apex_admin());
create policy "apex_logs_admin_read" on public.apex_logs
for select to authenticated using (public.is_apex_admin());
create policy "service_checks_admin_read" on public.service_checks
for select to authenticated using (public.is_apex_admin());

create policy "run_requests_admin_read" on public.run_requests
for select to authenticated using (public.is_apex_admin());
create policy "run_requests_admin_enqueue" on public.run_requests
for insert to authenticated
with check (public.is_apex_admin() and requested_by = auth.uid() and status = 'pending');

-- Explicit table privileges for the browser role. RLS still restricts the rows.
grant select on public.apex_admins to authenticated;
grant select, update on public.apex_settings to authenticated;
grant select, update on public.apex_prompts to authenticated;
grant select on public.paper_accounts, public.balance_ledger, public.system_runs,
  public.gemini_requests, public.trades, public.trade_events, public.apex_logs,
  public.service_checks to authenticated;
grant select, insert on public.run_requests to authenticated;

-- The backend uses the Supabase service role (server-side only), which bypasses RLS.
-- Seed singleton rows and the initial virtual account.
insert into public.apex_settings (id) values (1) on conflict (id) do nothing;
insert into public.apex_prompts (id) values (1) on conflict (id) do nothing;

do $$
declare
  v_account_id uuid;
begin
  select id into v_account_id from public.paper_accounts where is_active = true limit 1;
  if v_account_id is null then
    insert into public.paper_accounts (name, initial_balance, balance, is_active)
    values ('ApexPrime Paper Account', 20, 20, true)
    returning id into v_account_id;
    insert into public.balance_ledger (account_id, event_type, amount, balance_after, description)
    values (v_account_id, 'INITIAL_BALANCE', 20, 20, 'Saldo virtual inicial de 20 USDT');
  end if;
end $$;

comment on table public.trades is 'Paper trades only. No real exchange orders are submitted by this schema.';
comment on table public.balance_ledger is 'Append-only-style audit history for virtual balance movements.';
comment on table public.run_requests is 'Authenticated PWA command queue consumed by the local Redmi 6A Termux worker.';
comment on column public.apex_prompts.custom_chart_img_prompt is 'NULL means use the application default prompt.';
comment on column public.apex_prompts.custom_text_prompt is 'NULL means use the application default prompt.';
