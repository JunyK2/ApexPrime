-- ApexPrime migration 011.
-- Fee-aware protective stop state plus an immediate lock for the independent audio signal.
-- Safe to re-run. Trading remains paper-only.

alter table public.trades
  add column if not exists protective_stop_net_covered boolean not null default false,
  add column if not exists protective_stop_last_attempt_r numeric(12,5) not null default 0;

alter table public.trades
  drop constraint if exists trades_protective_stop_last_attempt_r_check,
  add constraint trades_protective_stop_last_attempt_r_check
    check (protective_stop_last_attempt_r >= 0);

comment on column public.trades.protective_stop_net_covered is
  'True only when the currently calculated protective stop is estimated to cover booked entry/exit fees, funding already charged and configured buffer. Gaps, slippage and future funding remain possible.';
comment on column public.trades.protective_stop_last_attempt_r is
  'Favourable R reached on the most recent fee-aware stop calculation; permits retry after another 0.25R if costs could not yet be covered.';


-- Resolve pgcrypto regardless of whether the existing Supabase project installed it
-- in `public` or `extensions`. Both schemas are present in this function search_path.
create or replace function public.apex_signal_unlock(p_pin text)
returns boolean
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
declare s public.device_signal_security%rowtype;
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  select * into s from public.device_signal_security where id=1 for update;
  if s.locked_until is not null and s.locked_until > now() then return false; end if;
  if p_pin is not null and crypt(p_pin, s.pin_hash) = s.pin_hash then
    update public.device_signal_security set is_unlocked=true, failed_attempts=0,
      locked_until=null, updated_at=now() where id=1;
    return true;
  end if;
  update public.device_signal_security set failed_attempts=failed_attempts+1,
    locked_until=case when failed_attempts+1 >= 5 then now()+interval '15 minutes' else null end,
    updated_at=now() where id=1;
  return false;
end;
$$;

revoke all on function public.apex_signal_unlock(text) from public;
grant execute on function public.apex_signal_unlock(text) to authenticated;

-- If the owner locks the sound panel while a command is playing, cancel PROCESSING
-- as well as PENDING. The Redmi controller sees the lock within its one-second poll.
create or replace function public.apex_signal_lock()
returns boolean
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  update public.device_signal_security
    set is_unlocked=false, continuous_wanted=false, updated_at=now()
    where id=1;
  update public.device_signal_commands
    set status='CANCELLED', completed_at=now(),
        error_message='Cancelado ao travar a função de sinal'
    where status in ('PENDING','PROCESSING');
  return true;
end;
$$;

revoke all on function public.apex_signal_lock() from public;
grant execute on function public.apex_signal_lock() to authenticated;

-- Do not queue one-shot/scheduled beeps while repeat mode is active; otherwise an
-- old scheduled request could fire unexpectedly after continuous mode is turned off.
create or replace function public.apex_signal_enqueue(p_scheduled_at timestamptz default null)
returns uuid
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
declare unlocked boolean; is_continuous boolean; command_id uuid;
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  select is_unlocked, continuous_wanted into unlocked, is_continuous
    from public.device_signal_security where id=1 for update;
  if not coalesce(unlocked,false) then raise exception 'A função de sinal está travada'; end if;
  if coalesce(is_continuous,false) then raise exception 'Desligue o som contínuo antes de enviar ou agendar um sinal único'; end if;
  if p_scheduled_at is not null and (p_scheduled_at <= now() or p_scheduled_at > now()+interval '30 days') then
    raise exception 'Agendamento deve ser futuro e limitado a 30 dias';
  end if;
  insert into public.device_signal_commands(action, scheduled_at, requested_by)
    values ('BEEP', p_scheduled_at, auth.uid()) returning id into command_id;
  return command_id;
end;
$$;

revoke all on function public.apex_signal_enqueue(timestamptz) from public;
grant execute on function public.apex_signal_enqueue(timestamptz) to authenticated;
