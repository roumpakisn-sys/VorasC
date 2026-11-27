begin;

alter table public.stadium_attendance
    add column if not exists did_work boolean not null default true,
    alter column arrival drop not null,
    alter column departure drop not null;

alter table public.stadium_attendance
    add constraint stadium_attendance_times_match_status check (
        (did_work and arrival is not null and departure is not null)
        or (not did_work and arrival is null and departure is null
            and break_minutes = 0 and worked_minutes = 0)
    );

create or replace function public.record_stadium_attendance(p_entries jsonb)
returns integer language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    entry record;
    assignment public.assignments%rowtype;
    saved_at timestamptz;
    duration integer;
    v_did_work boolean;
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
        assignment_notes text, did_work boolean
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

        v_did_work := coalesce(entry.did_work, true);
        if v_did_work then
            duration := mod(extract(epoch from (entry.departure - entry.arrival))::integer
                            + 86400, 86400) / 60;
            if duration is null or duration = 0 or entry.break_minutes is null
               or entry.break_minutes not between 0 and duration then
                raise exception 'Invalid attendance times';
            end if;
        else
            duration := 0;
            entry.arrival := null;
            entry.departure := null;
            entry.break_minutes := 0;
        end if;

        insert into public.stadium_attendance
            (assignment_id, project_id, employee_id, employee_name, work_date, arrival, departure,
             break_minutes, worked_minutes, area, notes, did_work)
        values
            (assignment.id, assignment."projectId", assignment."employeeId", entry.employee_name,
             assignment.date, entry.arrival, entry.departure, entry.break_minutes,
             duration - entry.break_minutes, coalesce(entry.area, ''), coalesce(entry.notes, ''), v_did_work)
        on conflict (assignment_id, project_id, employee_id, work_date) do update
            set employee_name = excluded.employee_name, arrival = excluded.arrival,
                departure = excluded.departure, break_minutes = excluded.break_minutes,
                worked_minutes = excluded.worked_minutes, area = excluded.area,
                notes = excluded.notes, did_work = excluded.did_work, updated_at = now();

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
