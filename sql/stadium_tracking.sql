begin;

create table if not exists public.stadium_attendance (
    assignment_id text not null,
    project_id text not null,
    employee_id text not null,
    employee_name text not null,
    work_date date not null,
    arrival time not null,
    departure time not null,
    break_minutes integer not null check (break_minutes between 0 and 1439),
    worked_minutes integer not null check (worked_minutes between 0 and 1439),
    area text not null default '',
    notes text not null default '',
    updated_at timestamptz not null default now(),
    primary key (assignment_id, project_id, employee_id, work_date)
);

create index if not exists stadium_attendance_work_date_idx
    on public.stadium_attendance (work_date, assignment_id);

create table if not exists public.stadium_tasks (
    id uuid primary key default gen_random_uuid(),
    work_date date not null,
    area text not null,
    category text not null,
    description text not null,
    team text not null default '',
    status text not null check (status in ('Εκκρεμεί', 'Σε εξέλιξη', 'Ολοκληρώθηκε')),
    notes text not null default '',
    updated_at timestamptz not null default now()
);

create index if not exists stadium_tasks_work_date_idx on public.stadium_tasks (work_date, id);

create table if not exists public.stadium_matches (
    match_date date not null,
    competition text not null check (competition in ('Πρωτάθλημα', 'Κύπελλο')),
    primary key (match_date, competition)
);

alter table public.stadium_attendance enable row level security;
alter table public.stadium_tasks enable row level security;
alter table public.stadium_matches enable row level security;
revoke all on public.stadium_attendance, public.stadium_tasks, public.stadium_matches
    from public, anon, authenticated;
grant select, insert, update on public.stadium_attendance, public.stadium_tasks, public.stadium_matches
    to service_role;

-- Home match dates from the supplied Πρωτάθλημα and Κύπελλο worksheets.
insert into public.stadium_matches (match_date, competition) values
    ('2026-08-30', 'Πρωτάθλημα'), ('2026-09-16', 'Κύπελλο'),
    ('2026-09-19', 'Πρωτάθλημα'), ('2026-10-11', 'Πρωτάθλημα'),
    ('2026-10-25', 'Πρωτάθλημα'), ('2026-11-07', 'Πρωτάθλημα'),
    ('2026-11-29', 'Πρωτάθλημα'), ('2026-12-02', 'Κύπελλο'),
    ('2026-12-20', 'Πρωτάθλημα'), ('2027-01-10', 'Πρωτάθλημα')
on conflict (match_date, competition) do nothing;

create or replace function public.record_stadium_attendance(p_entries jsonb)
returns integer language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    entry record;
    assignment public.assignments%rowtype;
    saved_at timestamptz;
    duration integer;
    total integer := 0;
begin
    if jsonb_typeof(p_entries) is distinct from 'array'
       or jsonb_array_length(p_entries) not between 1 and 80 then
        raise exception 'Invalid attendance batch';
    end if;

    -- Same lock order as the schedule's atomic writer. Both records commit together.
    lock table public.assignments in share row exclusive mode;
    for entry in select * from jsonb_to_recordset(p_entries) as r(
        expected jsonb, employee_name text, arrival time, departure time,
        break_minutes integer, area text, notes text, expected_attendance_at timestamptz,
        assignment_notes text
    ) loop
        select * into assignment from public.assignments where id = entry.expected->>'id';
        if not found or coalesce(assignment.is_cancelled, false)
           or nullif(assignment."employeeId", '') is null
           or to_jsonb(assignment) is distinct from
              to_jsonb(jsonb_populate_record(null::public.assignments, entry.expected)) then
            raise exception 'Stale or cancelled assignment';
        end if;

        select updated_at into saved_at from public.stadium_attendance
        where (assignment_id, project_id, employee_id, work_date) =
              (assignment.id, assignment."projectId", assignment."employeeId", assignment.date);
        if saved_at is distinct from entry.expected_attendance_at then
            raise exception 'Stale attendance';
        end if;

        duration := mod(extract(epoch from (entry.departure - entry.arrival))::integer
                        + 86400, 86400) / 60;
        if duration is null or duration = 0 or entry.break_minutes is null
           or entry.break_minutes not between 0 and duration then
            raise exception 'Invalid attendance times';
        end if;

        insert into public.stadium_attendance
            (assignment_id, project_id, employee_id, employee_name, work_date, arrival, departure,
             break_minutes, worked_minutes, area, notes)
        values
            (assignment.id, assignment."projectId", assignment."employeeId", entry.employee_name,
             assignment.date, entry.arrival, entry.departure, entry.break_minutes,
             duration - entry.break_minutes, coalesce(entry.area, ''), coalesce(entry.notes, ''))
        on conflict (assignment_id, project_id, employee_id, work_date) do update
            set employee_name = excluded.employee_name, arrival = excluded.arrival,
                departure = excluded.departure, break_minutes = excluded.break_minutes,
                worked_minutes = excluded.worked_minutes, area = excluded.area,
                notes = excluded.notes, updated_at = now();

        update public.assignments set notes = entry.assignment_notes, updated_at = now()
        where id = assignment.id;
        total := total + 1;
    end loop;
    return total;
end;
$$;

revoke all on function public.record_stadium_attendance(jsonb) from public, anon, authenticated;
grant execute on function public.record_stadium_attendance(jsonb) to service_role;

commit;
