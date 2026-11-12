-- STAFF.PRO: atomic replacement of multi-employee Gantt bars.
-- Run once in the Supabase SQL Editor after reviewing the function.
-- No existing assignments or projects are altered by installing the function.
-- The entire call (optional project + new shifts + old shifts removal + delta tombstones)
-- runs as a SINGLE PostgreSQL transaction. On any error PostgreSQL rolls it back.

create or replace function public.staffpro_replace_bar_atomic(
    p_originals jsonb,
    p_replacements jsonb,
    p_new_project jsonb default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $function$
declare
    v_original jsonb;
    v_new jsonb;
    v_current jsonb;
    v_key text;
    v_old_id text;
    v_old_ids text[] := array[]::text[];
    v_new_ids text[] := array[]::text[];
    v_a public.assignments%rowtype;
    v_p public.projects%rowtype;
    v_removed integer;
begin
    if p_originals is null or jsonb_typeof(p_originals) <> 'array'
        or p_replacements is null or jsonb_typeof(p_replacements) <> 'array'
        or jsonb_array_length(p_originals) < 1 or jsonb_array_length(p_originals) > 100
        or jsonb_array_length(p_replacements) < 1 or jsonb_array_length(p_replacements) > 100 then
        raise exception 'Invalid number of assignments for atomic Gantt replacement'
            using errcode = '22023';
    end if;

    -- Lock originals and compare every field that the editor loaded, including updated_at.
    -- This prevents overwriting another supervisor's changes.
    for v_original in select value from jsonb_array_elements(p_originals) loop
        if jsonb_typeof(v_original) <> 'object' or
            coalesce(v_original->>'id', '') = '' then
            raise exception 'Original assignment id is missing' using errcode = '22023';
        end if;
        v_old_id := v_original->>'id';
        if v_old_id = any(v_old_ids) then
            raise exception 'Duplicate original assignment' using errcode = '22023';
        end if;
        select to_jsonb(a) into v_current
        from public.assignments a
        where a.id::text = v_old_id
        for update;
        if v_current is null then
            raise exception 'Original assignment disappeared: %', v_old_id
                using errcode = '40001';
        end if;
        for v_key in select jsonb_object_keys(v_original) loop
            if v_current->v_key is distinct from v_original->v_key then
                raise exception 'Original assignment changed: % (%)', v_old_id, v_key
                    using errcode = '40001';
            end if;
        end loop;
        v_old_ids := array_append(v_old_ids, v_old_id);
    end loop;

    if p_new_project is not null and jsonb_typeof(p_new_project) <> 'null' then
        if jsonb_typeof(p_new_project) <> 'object' or
            coalesce(trim(p_new_project->>'name'), '') = '' or
            coalesce(p_new_project->>'id', '') = '' then
            raise exception 'Invalid new project' using errcode = '22023';
        end if;
        v_p := jsonb_populate_record(null::public.projects, p_new_project);
        insert into public.projects ("id", "name", "color")
        values (v_p."id", v_p."name", v_p."color");
    end if;

    -- A bulk INSERT statement is atomic within this function. All new IDs must differ
    -- from originals and from one another; avoid accidental upserts.
    for v_new in select value from jsonb_array_elements(p_replacements) loop
        if jsonb_typeof(v_new) <> 'object' or coalesce(v_new->>'id', '') = '' then
            raise exception 'New assignment id is missing' using errcode = '22023';
        end if;
        if (v_new->>'id') = any(v_old_ids) or (v_new->>'id') = any(v_new_ids) then
            raise exception 'Duplicate/reused new assignment id' using errcode = '22023';
        end if;
        v_a := jsonb_populate_record(null::public.assignments, v_new);
        insert into public.assignments (
            "id", "employeeId", "projectId", "date", "arrivalTime",
            "startTime", "endTime", "colorName", "colorHex", "notes",
            "is_cancelled", "cancel_reason", "recurring_id", "is_general"
        ) values (
            v_a."id", v_a."employeeId", v_a."projectId", v_a."date",
            v_a."arrivalTime", v_a."startTime", v_a."endTime",
            v_a."colorName", v_a."colorHex", v_a."notes",
            v_a."is_cancelled", v_a."cancel_reason", v_a."recurring_id",
            v_a."is_general"
        );
        v_new_ids := array_append(v_new_ids, v_new->>'id');
    end loop;

    delete from public.assignments a
    where a.id::text = any(v_old_ids);
    get diagnostics v_removed = row_count;
    if v_removed <> array_length(v_old_ids, 1) then
        raise exception 'Unexpected number of original assignments removed'
            using errcode = '40001';
    end if;

    -- Delta synchronization: other signed-in sessions must learn which old IDs vanished.
    insert into public.deleted_records (table_name, record_id)
    select 'assignments', unnest(v_old_ids);

    return jsonb_build_object(
        'ok', true,
        'removed', v_removed,
        'inserted', array_length(v_new_ids, 1)
    );
end;
$function$;

revoke all on function public.staffpro_replace_bar_atomic(jsonb,jsonb,jsonb) from public;
revoke all on function public.staffpro_replace_bar_atomic(jsonb,jsonb,jsonb) from anon;
revoke all on function public.staffpro_replace_bar_atomic(jsonb,jsonb,jsonb) from authenticated;
grant execute on function public.staffpro_replace_bar_atomic(jsonb,jsonb,jsonb) to service_role;
