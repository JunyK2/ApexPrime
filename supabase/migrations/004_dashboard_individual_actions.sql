-- ApexPrime migration 004: individual paper-trade exit and pending-entry cancellation.
-- Run once after 001, 002 and 003. This does not enable or add real exchange orders.

alter table public.run_requests
  drop constraint if exists run_requests_request_type_check;

alter table public.run_requests
  add constraint run_requests_request_type_check
  check (request_type in (
    'force_analysis',
    'close_open_trade',
    'close_trade',
    'cancel_pending_entry',
    'run_tests'
  ));

comment on column public.run_requests.request_type is
  'Authenticated PWA commands processed by the Redmi worker. All trade commands operate on virtual paper positions only.';
