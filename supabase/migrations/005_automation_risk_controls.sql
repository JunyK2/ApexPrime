-- ApexPrime migration 005: automatic trading pause and daily loss protection.
-- All controls apply to virtual paper trading only.

alter table public.apex_settings
  add column if not exists auto_trading_enabled boolean not null default true,
  add column if not exists max_daily_loss_pct numeric(6,3) not null default 6.000;

alter table public.apex_settings
  drop constraint if exists apex_settings_max_daily_loss_pct_check;

alter table public.apex_settings
  add constraint apex_settings_max_daily_loss_pct_check
  check (max_daily_loss_pct >= 0.5 and max_daily_loss_pct <= 20.000);

comment on column public.apex_settings.auto_trading_enabled is
  'Enables or pauses new simulated entries. Existing paper positions continue to be monitored and managed.';
comment on column public.apex_settings.max_daily_loss_pct is
  'Daily paper-account loss guard relative to initial_balance. New entries are blocked after the configured daily loss is reached.';
