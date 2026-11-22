-- ApexPrime migration 010: isolated Redmi 6A 440Hz square-wave signal controls.
-- This feature does not use Telegram and does not touch trading tables.
-- The supplied PIN is stored as a salted bcrypt hash, never as plaintext.

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.device_signal_security (
  id smallint primary key default 1 check (id = 1),
  pin_hash text not null,
  is_unlocked boolean not null default false,
  continuous_wanted boolean not null default false,
  failed_attempts integer not null default 0,
  locked_until timestamptz,
  updated_at timestamptz not null default now()
);

insert into public.device_signal_security(id, pin_hash, is_unlocked, continuous_wanted)
values (1, '$2a$12$OpNz2eJFi86hf7bOsrUY1.m9O5eIofdJxIemp4rt5pshOySLI0OOe', false, false)
on conflict (id) do nothing;

create table if not exists public.device_signal_commands (
  id uuid primary key default gen_random_uuid(),
  action text not null default 'BEEP' check (action in ('BEEP')),
  scheduled_at timestamptz,
  status text not null default 'PENDING' check (status in ('PENDING','PROCESSING','COMPLETED','FAILED','CANCELLED')),
  requested_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  result jsonb not null default '{}'::jsonb,
  error_message text
);
create index if not exists device_signal_commands_pending_idx
  on public.device_signal_commands(status, scheduled_at, created_at);

alter table public.device_signal_security enable row level security;
alter table public.device_signal_commands enable row level security;

-- No browser direct access to the PIN hash/security row. Only definer RPCs and service role can read it.
revoke all on public.device_signal_security from anon, authenticated;
revoke all on public.device_signal_commands from anon, authenticated;
grant select on public.device_signal_commands to authenticated;

do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='device_signal_commands' and policyname='device_signal_commands_admin_read') then
    create policy device_signal_commands_admin_read on public.device_signal_commands
      for select to authenticated using (public.is_apex_admin());
  end if;
end $$;

create or replace function public.apex_signal_get_state()
returns jsonb
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
declare s public.device_signal_security%rowtype;
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  select * into s from public.device_signal_security where id=1;
  return jsonb_build_object(
    'is_unlocked', coalesce(s.is_unlocked,false),
    'continuous_wanted', coalesce(s.continuous_wanted,false),
    'locked_until', s.locked_until,
    'updated_at', s.updated_at
  );
end;
$$;

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

create or replace function public.apex_signal_lock()
returns boolean
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  update public.device_signal_security set is_unlocked=false, continuous_wanted=false, updated_at=now() where id=1;
  update public.device_signal_commands set status='CANCELLED', completed_at=now(),
    error_message='Cancelado ao travar a função de sinal'
    where status in ('PENDING','PROCESSING');
  return true;
end;
$$;

create or replace function public.apex_signal_set_continuous(p_enabled boolean)
returns boolean
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
declare unlocked boolean;
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  select is_unlocked into unlocked from public.device_signal_security where id=1 for update;
  if p_enabled and not coalesce(unlocked,false) then raise exception 'Destrave a função de sinal antes de ativar'; end if;
  update public.device_signal_security set continuous_wanted=p_enabled, updated_at=now() where id=1;
  return p_enabled;
end;
$$;

create or replace function public.apex_signal_enqueue(p_scheduled_at timestamptz default null)
returns uuid
language plpgsql
security definer
set search_path = public, extensions, auth
as $$
declare unlocked boolean; command_id uuid;
begin
  if not public.is_apex_admin() then raise exception 'not authorized'; end if;
  select is_unlocked into unlocked from public.device_signal_security where id=1 for update;
  if not coalesce(unlocked,false) then raise exception 'A função de sinal está travada'; end if;
  if p_scheduled_at is not null and (p_scheduled_at <= now() or p_scheduled_at > now()+interval '30 days') then
    raise exception 'Agendamento deve ser futuro e limitado a 30 dias';
  end if;
  insert into public.device_signal_commands(action, scheduled_at, requested_by)
    values ('BEEP', p_scheduled_at, auth.uid()) returning id into command_id;
  return command_id;
end;
$$;

revoke all on function public.apex_signal_get_state() from public;
revoke all on function public.apex_signal_unlock(text) from public;
revoke all on function public.apex_signal_lock() from public;
revoke all on function public.apex_signal_set_continuous(boolean) from public;
revoke all on function public.apex_signal_enqueue(timestamptz) from public;
grant execute on function public.apex_signal_get_state() to authenticated;
grant execute on function public.apex_signal_unlock(text) to authenticated;
grant execute on function public.apex_signal_lock() to authenticated;
grant execute on function public.apex_signal_set_continuous(boolean) to authenticated;
grant execute on function public.apex_signal_enqueue(timestamptz) to authenticated;

