-- ApexPrime migration 009: separate AI automation switch and momentum/protection profile.
-- Safe to re-run. Applies to paper trading only.

alter table public.apex_settings
  add column if not exists ai_auto_analysis_enabled boolean not null default true,
  add column if not exists prompt_profile text not null default 'standard',
  add column if not exists profit_stop_buffer_bps numeric(8,3) not null default 5.000;

alter table public.apex_settings
  drop constraint if exists apex_settings_prompt_profile_check,
  add constraint apex_settings_prompt_profile_check
    check (prompt_profile in ('standard','momentum_protection')),
  drop constraint if exists apex_settings_profit_stop_buffer_bps_check,
  add constraint apex_settings_profit_stop_buffer_bps_check
    check (profit_stop_buffer_bps between 0 and 100);

-- Groq is reserved for operational health/reporting and compact post-trade summaries.
-- It is no longer an analysis strategy provider.
update public.apex_settings
set fixed_ai_provider = 'gemini'
where fixed_ai_provider = 'groq';

alter table public.apex_settings
  drop constraint if exists apex_settings_fixed_ai_provider_check,
  add constraint apex_settings_fixed_ai_provider_check
    check (fixed_ai_provider in ('gemini','openrouter'));

comment on column public.apex_settings.ai_auto_analysis_enabled is
  'When false, automatic market scans still detect/log opportunities and notify Telegram, but do not send charts or text to Gemini/OpenRouter. Manual analyses remain explicit user actions; Groq health/reports continue.';
comment on column public.apex_settings.prompt_profile is
  'standard uses the existing institutional prompt; momentum_protection uses the experimental immediate-entry and nearest-structural-target profile.';
comment on column public.apex_settings.profit_stop_buffer_bps is
  'Additional stop distance beyond fee/funding break-even, in basis points; a net-positive stop is not guaranteed through gaps or slippage.';

