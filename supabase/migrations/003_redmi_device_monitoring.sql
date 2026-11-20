-- ApexPrime migration 003: Redmi/Termux server telemetry and online history.
-- Execute once in Supabase SQL Editor after migrations 001 and 002.

create table if not exists public.apex_devices (
  device_id text primary key,
  device_name text not null,
  device_model text,
  android_version text,
  status text not null default 'OFFLINE' check (status in ('ONLINE','OFFLINE','DEGRADED')),
  battery_percentage integer check (battery_percentage is null or battery_percentage between 0 and 100),
  battery_status text,
  battery_plugged text,
  is_charging boolean,
  battery_temperature_c numeric(5,2),
  battery_health text,
  wifi_ssid text,
  wifi_rssi_dbm integer,
  wifi_link_speed_mbps numeric(10,2),
  wifi_frequency_mhz numeric(10,2),
  wifi_ip inet,
  wifi_connected boolean,
  uptime_seconds bigint,
  last_seen_at timestamptz,
  last_telemetry_at timestamptz,
  low_battery_alert_active boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.device_heartbeats (
  id bigint generated always as identity primary key,
  device_id text not null references public.apex_devices(device_id) on delete cascade,
  seen_at timestamptz not null default now(),
  network_online boolean not null default true,
  worker_status text not null default 'RUNNING',
  metadata jsonb not null default '{}'::jsonb
);
create index if not exists device_heartbeats_device_seen_idx
  on public.device_heartbeats(device_id, seen_at desc);

create table if not exists public.device_events (
  id uuid primary key default gen_random_uuid(),
  device_id text not null references public.apex_devices(device_id) on delete cascade,
  event_type text not null check (event_type in (
    'SERVICE_STARTED','SERVICE_STOPPED','ONLINE','OFFLINE_GAP','LOW_BATTERY_ALERT',
    'BATTERY_RECOVERED','WIFI_CHANGED','ERROR','REBOOT'
  )),
  occurred_at timestamptz not null default now(),
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists device_events_device_time_idx
  on public.device_events(device_id, occurred_at desc);

create or replace function public.set_device_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;
drop trigger if exists apex_devices_updated_at on public.apex_devices;
create trigger apex_devices_updated_at before update on public.apex_devices
for each row execute function public.set_device_updated_at();

alter table public.apex_devices enable row level security;
alter table public.device_heartbeats enable row level security;
alter table public.device_events enable row level security;

drop policy if exists apex_devices_admin_read on public.apex_devices;
create policy apex_devices_admin_read on public.apex_devices
for select to authenticated using (public.is_apex_admin());
drop policy if exists device_heartbeats_admin_read on public.device_heartbeats;
create policy device_heartbeats_admin_read on public.device_heartbeats
for select to authenticated using (public.is_apex_admin());
drop policy if exists device_events_admin_read on public.device_events;
create policy device_events_admin_read on public.device_events
for select to authenticated using (public.is_apex_admin());

grant select on public.apex_devices, public.device_heartbeats, public.device_events to authenticated;
grant select, insert, update, delete on public.apex_devices, public.device_heartbeats, public.device_events to service_role;
grant usage, select on sequence public.device_heartbeats_id_seq to service_role;

comment on table public.apex_devices is 'Latest device/server health state reported by the Redmi 6A Termux daemon.';
comment on table public.device_heartbeats is 'Append-only heartbeat history; online/offline timeline is inferred from gaps.';
comment on table public.device_events is 'Device events, including estimated outages, low battery alerts and Wi-Fi changes.';
