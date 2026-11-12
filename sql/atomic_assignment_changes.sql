-- Apply BEFORE deploying the Python changes, using the Supabase SQL Editor.
-- Requires the existing assignments, employees, leaves, projects,
-- deleted_records and employee_availability_rules tables. No data is rewritten.
begin;

create table if not exists public.assignment_write_receipts (
    request_id uuid primary key,
    payload jsonb not null,
    result jsonb not null,
    created_at timestamptz not null default now()
);
alter table public.assignment_write_receipts enable row level security;
revoke all on public.assignment_write_receipts from public, anon, authenticated;
grant select, insert on public.assignment_write_receipts to service_role;

create or replace function public.assignment_validation_context(
    p_employee_ids jsonb, p_first date, p_last date
) returns jsonb language sql volatile security invoker set search_path = public, pg_temp as $$
    select jsonb_build_object(
        'employee_ids', p_employee_ids, 'first', p_first, 'last', p_last,
        'assignments', coalesce((select jsonb_agg(to_jsonb(a) order by a.id)
            from public.assignments a where a."employeeId"::text in
                (select jsonb_array_elements_text(p_employee_ids))
                and a.date::date between p_first and p_last), '[]'::jsonb),
        'leaves', coalesce((select jsonb_agg(to_jsonb(l) order by l.id)
            from public.leaves l where l."employeeId"::text in
                (select jsonb_array_elements_text(p_employee_ids))
                and l."startDate"::date <= p_last and l."endDate"::date >= p_first), '[]'::jsonb),
        'employees', coalesce((select jsonb_agg(to_jsonb(e) order by e.id)
            from public.employees e where e.id::text in
                (select jsonb_array_elements_text(p_employee_ids))), '[]'::jsonb),
        'rules', coalesce((select jsonb_agg(to_jsonb(r) order by r.id)
            from public.employee_availability_rules r where r.employee_id::text in
                (select jsonb_array_elements_text(p_employee_ids))), '[]'::jsonb)
    );
$$;

create or replace function public.assignment_write_result(p_request_id uuid)
returns jsonb language sql stable security invoker set search_path = public, pg_temp as $$
    select result from public.assignment_write_receipts where request_id = p_request_id;
$$;

create or replace function public.save_assignment_changes(
    p_request_id uuid, p_expected jsonb, p_records jsonb,
    p_project jsonb default null, p_context jsonb default null
) returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_payload jsonb := jsonb_build_object('expected', p_expected, 'records', p_records,
                                         'project', p_project, 'context', p_context);
    v_receipt public.assignment_write_receipts%rowtype;
    v_old public.assignments%rowtype;
    v_row jsonb;
    v_cols text;
    v_sets text;
    v_result jsonb;
    v_deleted jsonb := '[]'::jsonb;
    v_count integer;
    v_active_change boolean;
begin
    -- Serialize concurrent replays even when no receipt exists yet.
    perform pg_advisory_xact_lock(hashtextextended(p_request_id::text, 0));
    select * into v_receipt from public.assignment_write_receipts where request_id = p_request_id;
    if found then
        if v_receipt.payload <> v_payload then
            raise exception 'Request ID reused with different data';
        end if;
        return v_receipt.result;
    end if;
    if jsonb_typeof(p_expected) is distinct from 'array'
       or jsonb_typeof(p_records) is distinct from 'array'
       or jsonb_array_length(p_expected) > 80
       or jsonb_array_length(p_records) not between 1 and (case when jsonb_array_length(p_expected) = 0 then 5000 else 80 end) then
        raise exception 'Expected arrays containing at most 80 assignments';
    end if;
    if exists(select 1 from jsonb_array_elements(p_expected) r group by r->>'id' having count(*) > 1)
       or exists(select 1 from jsonb_array_elements(p_records) r group by r->>'id' having count(*) > 1)
       or exists(select 1 from jsonb_array_elements(p_expected || p_records) r where coalesce(r->>'id', '') = '') then
        raise exception 'Missing or duplicate assignment IDs';
    end if;

    -- These locks also exclude legacy REST writers while checking the snapshot.
    -- Short bounded transaction, no HTTP calls or per-row commits inside it.
    lock table public.assignments in share row exclusive mode;
    lock table public.employees, public.leaves, public.employee_availability_rules in share mode;
    for v_row in select value from jsonb_array_elements(p_expected) loop
        select * into v_old from public.assignments where id::text = v_row->>'id';
        if not found then
            raise exception 'Assignment removed: %', v_row->>'id';
        end if;
        if to_jsonb(v_old) <> to_jsonb(jsonb_populate_record(null::public.assignments, v_row)) then
            raise exception 'Stale assignment: %', v_row->>'id';
        end if;
    end loop;

    for v_row in select value from jsonb_array_elements(p_records) loop
        if exists(select 1 from jsonb_object_keys(v_row) k where k not in (
            'id', 'employeeId', 'projectId', 'date', 'startTime', 'endTime', 'arrivalTime',
            'colorName', 'colorHex', 'notes', 'is_cancelled', 'cancel_reason', 'recurring_id', 'is_general')) then
            raise exception 'Unexpected assignment field';
        end if;
        if nullif(v_row->>'date', '') is null or nullif(v_row->>'startTime', '') is null
           or nullif(v_row->>'endTime', '') is null
           or (v_row->>'startTime')::time = (v_row->>'endTime')::time then
            raise exception 'Invalid assignment interval';
        end if;
        select * into v_old from public.assignments where id::text = v_row->>'id';
        if found and not exists(select 1 from jsonb_array_elements(p_expected) r where r->>'id' = v_row->>'id') then
            raise exception 'New assignment ID already exists';
        end if;
        v_active_change := coalesce(v_row->>'employeeId', '') <> '' and not coalesce((v_row->>'is_cancelled')::boolean, false)
            and (v_old.id is null or coalesce(v_old.is_cancelled, false)
                or v_old."employeeId"::text is distinct from v_row->>'employeeId'
                or v_old.date::date is distinct from (v_row->>'date')::date
                or v_old."startTime"::time is distinct from (v_row->>'startTime')::time
                or v_old."endTime"::time is distinct from (v_row->>'endTime')::time);
        if v_active_change and (
            p_context is null or not coalesce((p_context->'employee_ids') ? (v_row->>'employeeId'), false)
            or (p_context->>'first')::date > (v_row->>'date')::date - 1
            or (p_context->>'last')::date < (v_row->>'date')::date
                + case when (v_row->>'endTime')::time < (v_row->>'startTime')::time then 1 else 0 end
        ) then
            raise exception 'Missing validation scope';
        end if;
    end loop;
    if p_context is not null and (not (p_context ?& array['employee_ids', 'first', 'last', 'assignments', 'employees', 'leaves', 'rules'])
        or jsonb_typeof(p_context->'employee_ids') is distinct from 'array'
        or p_context->>'first' is null or p_context->>'last' is null) then
        raise exception 'Incomplete validation snapshot';
    end if;
    if p_context is not null and public.assignment_validation_context(
        p_context->'employee_ids', (p_context->>'first')::date, (p_context->>'last')::date
    ) is distinct from p_context then
        raise exception 'Availability changed; reload and validate again';
    end if;

    if p_project is not null then
        insert into public.projects (id, name, color)
            select id, name, color from jsonb_populate_record(null::public.projects, p_project);
    end if;
    for v_row in select value from jsonb_array_elements(p_records) loop
        -- Server timestamp drives incremental synchronization; preserve all other
        -- columns/defaults not present in the editable payload.
        if exists(select 1 from pg_attribute where attrelid = 'public.assignments'::regclass
                  and attname = 'updated_at' and not attisdropped) then
            v_row := v_row || jsonb_build_object('updated_at', clock_timestamp());
        end if;
        if exists(select 1 from jsonb_array_elements(p_expected) r where r->>'id' = v_row->>'id') then
            select string_agg(format('%I = r.%I', k, k), ', ' order by k) into v_sets
                from jsonb_object_keys(v_row) k where k <> 'id';
            execute format('update public.assignments a set %s from jsonb_populate_record(null::public.assignments, $1) r where a.id = r.id', v_sets) using v_row;
        else
            select string_agg(format('%I', k), ', ' order by k) into v_cols from jsonb_object_keys(v_row) k;
            execute format('insert into public.assignments (%s) select %s from jsonb_populate_record(null::public.assignments, $1)', v_cols, v_cols) using v_row;
        end if;
        get diagnostics v_count = row_count;
        if v_count <> 1 then
            raise exception 'Assignment write did not affect exactly one row';
        end if;
    end loop;
    for v_row in select value from jsonb_array_elements(p_expected) loop
        if not exists(select 1 from jsonb_array_elements(p_records) r where r->>'id' = v_row->>'id') then
            delete from public.assignments where id::text = v_row->>'id';
            get diagnostics v_count = row_count;
            if v_count <> 1 then
                raise exception 'Assignment deletion did not affect exactly one row';
            end if;
            insert into public.deleted_records (table_name, record_id)
                select table_name, record_id from jsonb_populate_record(null::public.deleted_records,
                    jsonb_build_object('table_name', 'assignments', 'record_id', v_row->>'id'));
            v_deleted := v_deleted || jsonb_build_array(v_row->>'id');
        end if;
    end loop;
    select jsonb_build_object('request_id', p_request_id, 'deleted_ids', v_deleted,
        'rows', coalesce(jsonb_agg(to_jsonb(a) order by a.id), '[]'::jsonb), 'project', p_project)
        into v_result from public.assignments a
        where a.id::text in (select r->>'id' from jsonb_array_elements(p_records) r);
    insert into public.assignment_write_receipts (request_id, payload, result) values (p_request_id, v_payload, v_result);
    return v_result;
end;
$$;

revoke all on function public.assignment_validation_context(jsonb, date, date) from public, anon, authenticated;
revoke all on function public.assignment_write_result(uuid) from public, anon, authenticated;
revoke all on function public.save_assignment_changes(uuid, jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.assignment_validation_context(jsonb, date, date) to service_role;
grant execute on function public.assignment_write_result(uuid) to service_role;
grant execute on function public.save_assignment_changes(uuid, jsonb, jsonb, jsonb, jsonb) to service_role;
commit;
