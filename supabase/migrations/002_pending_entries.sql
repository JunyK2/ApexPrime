-- ApexPrime | Pending paper entries | run once after 001_initial_schema.sql
-- Adds simulated pullback/confirmation setups. It does not create real exchange orders.

create table if not exists public.pending_entries (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.paper_accounts(id) on delete restrict,
  run_id uuid references public.system_runs(id) on delete set null,
  symbol text not null default 'BTCUSDT',
  direction text not null check (direction in ('LONG','SHORT')),
  entry_type text not null check (entry_type in ('PULLBACK','CONFIRMACAO')),
  status text not null default 'PENDING'
    check (status in ('PENDING','PROCESSING','FILLED','EXPIRED','CANCELLED')),
  entry_price numeric(20,8) not null check (entry_price > 0),
  stop_loss numeric(20,8) not null check (stop_loss > 0),
  tp1_price numeric(20,8) not null check (tp1_price > 0),
  tp2_price numeric(20,8) not null check (tp2_price > 0),
  confidence text check (confidence in ('BAIXA','MEDIA','ALTA')),
  score numeric(5,2) check (score is null or score between 0 and 10),
  regime text check (regime in ('TENDENCIA','RANGE','TRANSICAO')),
  strategy_name text,
  analysis_summary text,
  expires_at timestamptz not null,
  last_checked_at timestamptz not null default now(),
  filled_trade_id uuid references public.trades(id) on delete set null,
  resolution_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (direction <> 'LONG' or (stop_loss < entry_price and tp1_price > entry_price and tp2_price > tp1_price)),
  check (direction <> 'SHORT' or (stop_loss > entry_price and tp1_price < entry_price and tp2_price < tp1_price)),
  check ((status = 'FILLED' and filled_trade_id is not null) or status <> 'FILLED')
);

create index if not exists pending_entries_status_created_idx
  on public.pending_entries (status, created_at asc);
create index if not exists pending_entries_account_status_idx
  on public.pending_entries (account_id, status);
create index if not exists pending_entries_expiry_idx
  on public.pending_entries (expires_at) where status in ('PENDING','PROCESSING');

alter table public.pending_entries enable row level security;
drop policy if exists "pending_entries_admin_read" on public.pending_entries;
create policy "pending_entries_admin_read" on public.pending_entries
  for select to authenticated using (public.is_apex_admin());
grant select on public.pending_entries to authenticated;

drop trigger if exists pending_entries_updated_at on public.pending_entries;
create trigger pending_entries_updated_at before update on public.pending_entries
for each row execute function public.set_updated_at();

comment on table public.pending_entries is
  'Simulated pullback/confirmation setups waiting for a future market event; no real exchange orders.';


-- Independent market-data cursor: updated_at is touched by ordinary row updates
-- and must never be used to resume 1m candle processing.
alter table public.trades
  add column if not exists last_market_candle_at timestamptz;

update public.trades
set last_market_candle_at = opened_at
where last_market_candle_at is null;

create index if not exists trades_open_market_cursor_idx
  on public.trades (status, last_market_candle_at)
  where status = 'OPEN';
