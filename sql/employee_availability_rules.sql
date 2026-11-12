-- STAFF.PRO: optional working-time restrictions/preferences.
-- Execute once in the Supabase SQL Editor. Does NOT modify employees,
-- assignments, leaves or recurring_patterns.
create table if not exists public.employee_availability_rules (
    id uuid primary key default gen_random_uuid(),
    employee_id text not null,
    scope text not null check (scope in ('weekday', 'date')),
    weekday smallint check (weekday between 0 and 6),
    rule_date date,
    kind text not null check (kind in ('unavailable', 'only_available', 'preferred')),
    start_time text,
    end_time text,
    note text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    constraint valid_scope check (
        (scope = 'weekday' and weekday is not null and rule_date is null)
        or (scope = 'date' and rule_date is not null and weekday is null)
    ),
    constraint both_times check (
        (start_time is null and end_time is null)
        or (start_time is not null and end_time is not null)
    )
);
create index if not exists employee_availability_rules_employee
    on public.employee_availability_rules (employee_id, scope, weekday, rule_date);

-- These records are private workforce information: only the server-side
-- Supabase service-role client should access them. Never use a service-role
-- key in a browser or commit it to GitHub.
alter table public.employee_availability_rules enable row level security;
revoke all on table public.employee_availability_rules from anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update, delete on public.employee_availability_rules to service_role;
