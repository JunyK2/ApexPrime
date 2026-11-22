-- ApexPrime migration 008: OpenRouter diagnostics + browser permissions.
-- Execute once after the currently installed migrations. Safe to re-run.

alter table public.service_checks drop constraint if exists service_checks_service_check;
alter table public.service_checks add constraint service_checks_service_check
  check (service in ('BINANCE','SUPABASE','GEMINI','OPENROUTER','GROQ','CHART_IMG','TELEGRAM','TEXT_GENERATOR'));

-- Ensure expanded tables remain readable only by the authenticated ApexPrime admin.
do $$
begin
  if to_regclass('public.ai_requests') is not null then
    alter table public.ai_requests enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='ai_requests' and policyname='ai_requests_admin_read') then
      create policy ai_requests_admin_read on public.ai_requests for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
  if to_regclass('public.trade_reviews') is not null then
    alter table public.trade_reviews enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='trade_reviews' and policyname='trade_reviews_admin_read') then
      create policy trade_reviews_admin_read on public.trade_reviews for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
  if to_regclass('public.apex_exports') is not null then
    alter table public.apex_exports enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='apex_exports' and policyname='apex_exports_admin_read') then
      create policy apex_exports_admin_read on public.apex_exports for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
  if to_regclass('public.opportunity_events') is not null then
    alter table public.opportunity_events enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='opportunity_events' and policyname='opportunity_events_admin_read') then
      create policy opportunity_events_admin_read on public.opportunity_events for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
  if to_regclass('public.market_snapshots') is not null then
    alter table public.market_snapshots enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='market_snapshots' and policyname='market_snapshots_admin_read') then
      create policy market_snapshots_admin_read on public.market_snapshots for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
  if to_regclass('public.groq_reports') is not null then
    alter table public.groq_reports enable row level security;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='groq_reports' and policyname='groq_reports_admin_read') then
      create policy groq_reports_admin_read on public.groq_reports for select to authenticated using (public.is_apex_admin());
    end if;
  end if;
end $$;

grant select on public.ai_requests, public.trade_reviews, public.apex_exports,
  public.opportunity_events, public.market_snapshots, public.groq_reports to authenticated;
grant select, insert on public.run_requests to authenticated;
grant select on public.device_heartbeats, public.apex_devices, public.device_events to authenticated;
grant select on public.trades, public.trade_events, public.pending_entries,
  public.paper_accounts, public.balance_ledger, public.system_runs,
  public.gemini_requests, public.apex_logs, public.service_checks,
  public.apex_settings, public.apex_prompts to authenticated;

create index if not exists ai_requests_provider_created_idx on public.ai_requests(provider, created_at desc);
create index if not exists apex_exports_created_idx on public.apex_exports(created_at desc);
create index if not exists opportunity_events_candle_idx on public.opportunity_events(candle_open_time desc);
