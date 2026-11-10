"""STAFF.PRO | Smart replacement assistant.

Install together with replacement_engine.py in repository root.
Optional location preference requires sql/add_replacement_regions.sql migration.
Does not modify any other Gantt, Viber, leave or export functionality.
"""
import streamlit as st

st.set_page_config(page_title="Έξυπνες Αντικαταστάσεις | STAFF.PRO", page_icon="🧩", layout="wide")

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import utils
from replacement_engine import (
    as_date,
    candidate_assessment,
    empty_shifts,
    interval,
    is_cancelled,
    rank_candidates,
)


if not st.session_state.get("authenticated", False):
    st.switch_page("streamlit_app.py")
    st.stop()

for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    if key not in st.session_state:
        st.session_state[key] = []

utils.init_data_and_sync()
utils.setup_shared_ui()


def local_today():
    return datetime.now(ZoneInfo("Europe/Athens")).date()


def lookup_name(records, item_id, fallback="Άγνωστο"):
    return next(
        (str(x.get("name") or fallback) for x in records if str(x.get("id")) == str(item_id)),
        fallback,
    )


def region_for_project(project_id):
    return next(
        (str(x.get("region") or "").strip()
         for x in st.session_state.projects if str(x.get("id")) == str(project_id)),
        "",
    )


def shift_label(a):
    project = lookup_name(st.session_state.projects, a.get("projectId"), "Άγνωστο έργο")
    return f"{project} • {str(a.get('startTime') or '')[:5]}–{str(a.get('endTime') or '')[:5]} • θέση {str(a.get('id'))[:8]}"


def read_db_row(table, record_id):
    response = (
        utils.supabase.table(table).select("*")
        .eq("id", record_id).limit(1).execute()
    )
    return (response.data or [None])[0]


def update_region(table, record_id, new_region):
    """Save region only if migration exists; avoid a false 'saved' notice."""
    if not utils.supabase:
        st.error("Δεν υπάρχει ενεργή σύνδεση με τη Supabase.")
        return
    try:
        res = utils.supabase.table(table).update(
            {"region": new_region.strip() or None}
        ).eq("id", record_id).execute()
        if not res.data:
            st.error("Η περιοχή δεν αποθηκεύτηκε. Έλεγξε τα δικαιώματα στη Supabase.")
            return
    except Exception as exc:
        st.error(
            "Δεν αποθηκεύτηκε η περιοχή. Αν δεν έχεις εκτελέσει το SQL "
            "για τις περιοχές, εκτέλεσέ το πρώτα. "
            f"Λεπτομέρειες: {exc}"
        )
        return
    local_rows = st.session_state.get(table, [])
    current = next((v for v in local_rows if str(v.get("id")) == str(record_id)), None)
    if current is not None:
        before = dict(current)
        current["region"] = new_region.strip() or None
        utils.add_transaction([
            {"type": "update", "table": table, "old_records": [before], "new_records": [dict(current)]}
        ])
    utils.mark_data_changed()
    utils.touch_app_sync_state()
    utils.log_activity("ΠΕΡΙΟΧΗ", table, f"Ενημερώθηκε η περιοχή για εγγραφή {str(record_id)[:8]}")
    st.success("Η περιοχή αποθηκεύτηκε.")
    st.rerun()


def assign_replacement(vacant, selected_employee, options):
    """Reload authoritative records and perform guarded one-row update.

    Does not change any project's recurring template, calendar or other employees.
    The target must STILL be empty to be updated.
    """
    if not utils.supabase:
        st.error("Απαιτείται σύνδεση Supabase για ασφαλή αποθήκευση.")
        return
    if st.session_state.get("current_user") == "TAN":
        st.error("Ο χρήστης έχει δικαιώματα μόνο ανάγνωσης.")
        return

    try:
        target = read_db_row("assignments", vacant["id"])
        fresh_emp = read_db_row("employees", selected_employee["id"])
        if not target or not fresh_emp:
            st.error("Η βάρδια ή ο εργαζόμενος δεν υπάρχουν πλέον στη βάση.")
            return
        if target.get("employeeId") not in (None, "") or is_cancelled(target):
            st.error("Η βάρδια έχει ήδη καλυφθεί ή ακυρωθεί από άλλο χρήστη. Κάνε ανανέωση.")
            return
        if (str(target.get("projectId")) != str(vacant.get("projectId"))
            or as_date(target.get("date")) != as_date(vacant.get("date"))
            or str(target.get("startTime"))[:5] != str(vacant.get("startTime"))[:5]
            or str(target.get("endTime"))[:5] != str(vacant.get("endTime"))[:5]):
            st.error("Το έργο ή το ωράριο άλλαξε στο μεταξύ. Ανανεώνουμε τις προτάσεις πριν τη νέα ανάθεση.")
            return
        if fresh_emp.get("status", "Ενεργός") != "Ενεργός":
            st.error("Ο εργαζόμενος δεν είναι πλέον ενεργός.")
            return
        if options["only_external"] and not fresh_emp.get("is_external_crew", False):
            st.error("Ο εργαζόμενος δεν ανήκει πλέον στο εξωτερικό συνεργείο.")
            return

        shift_date = as_date(target.get("date"))
        day_before = shift_date - timedelta(days=1)
        day_after = shift_date + timedelta(days=1)
        busy_resp = (
            utils.supabase.table("assignments").select("*")
            .eq("employeeId", fresh_emp["id"])
            .gte("date", day_before.isoformat())
            .lte("date", day_after.isoformat()).execute()
        )
        leave_resp = (
            utils.supabase.table("leaves").select("*")
            .eq("employeeId", fresh_emp["id"])
            .lte("startDate", day_after.isoformat())
            .gte("endDate", shift_date.isoformat()).execute()
        )
        project = read_db_row("projects", target.get("projectId"))
        project_region = (project or {}).get("region", "")
        report = candidate_assessment(
            fresh_emp, target, busy_resp.data or [], leave_resp.data or [],
            project_region or "",
            travel_buffer_minutes=options["travel_buffer_minutes"],
            maximum_day_hours=options["maximum_day_hours"],
            require_same_region=options["require_same_region"],
            today=local_today(),
        )
        if not report["eligible"]:
            st.error(f"Δεν έγινε ανάθεση. Ο εργαζόμενος δεν είναι πλέον διαθέσιμος: {report['reason']}")
            return

        query = (
            utils.supabase.table("assignments")
            .update({"employeeId": fresh_emp["id"]})
            .eq("id", target["id"])
        )
        # Conditional guard: do not overwrite another user's assignment.
        if target.get("employeeId") is None:
            query = query.is_("employeeId", "null")
        else:
            query = query.eq("employeeId", "")
        updated_result = query.execute()
        updated_rows = updated_result.data or []
        if len(updated_rows) != 1 or str(updated_rows[0].get("employeeId")) != str(fresh_emp["id"]):
            st.error("Η βάρδια άλλαξε από άλλο χρήστη ή δεν αποθηκεύτηκε. Δεν έγινε ανάθεση.")
            return

        # Local state and undo are updated ONLY after verified DB success.
        local_a = next(
            (a for a in st.session_state.assignments if str(a.get("id")) == str(target["id"])),
            None,
        )
        before = dict(local_a) if local_a is not None else dict(target)
        if local_a is not None:
            local_a["employeeId"] = fresh_emp["id"]
        else:
            new_local = dict(updated_rows[0])
            new_local["date"] = as_date(new_local.get("date"))
            st.session_state.assignments.append(new_local)
        after = {**before, "employeeId": fresh_emp["id"]}
        utils.add_transaction([{
            "type": "update", "table": "assignments",
            "old_records": [before], "new_records": [after],
        }])
        utils.mark_data_changed()
        utils.touch_app_sync_state()
        utils.log_activity(
            "ΕΞΥΠΝΗ ΑΝΤΙΚΑΤΑΣΤΑΣΗ", "assignments",
            f"{fresh_emp.get('name', '')} → "
            f"{(project or {}).get('name', 'Έργο')} | {shift_date:%d/%m/%Y} | "
            f"{target.get('startTime')}–{target.get('endTime')}"
        )
        st.session_state["smart_replacement_success"] = (
            f"Η βάρδια ανατέθηκε στον/στην {fresh_emp.get('name', '')}. "
            "Η αλλαγή καταχωρήθηκε στη Supabase."
        )
        st.session_state.last_sync_time = None  # Force fresh data on next render.
        st.rerun()
    except Exception as exc:
        st.error(f"Η ανάθεση δεν ολοκληρώθηκε. Δεν θα θεωρηθεί επιτυχής: {exc}")


st.title("🧩 Έξυπνος βοηθός αντικαταστάσεων")
st.caption("Προτάσεις για ακάλυπτες βάρδιες με βάση πραγματικά ωράρια, άδειες, περιοχές και ιστορικό έργων.")

if st.session_state.pop("smart_replacement_success", None) is not None:
    # It is a confirmation of the successful DB update in the previous run.
    st.success("Η τελευταία αντικατάσταση αποθηκεύτηκε στη Supabase.")

selected_date = st.date_input("📅 Ημερομηνία προς κάλυψη", value=local_today(), key="smart_replace_day")

st.markdown("#### ⚙️ Κριτήρια επιλογής")
c1, c2, c3, c4 = st.columns(4)
with c1:
    only_external = st.checkbox("Μόνο εξωτερικό συνεργείο", value=False, key="smart_only_external")
with c2:
    travel_buffer = st.selectbox("Ελάχιστο κενό μεταξύ βαρδιών", [0, 15, 30, 60, 90], index=2, format_func=lambda v: f"{v} λεπτά", key="smart_travel_buffer")
with c3:
    max_day_hours = st.selectbox("Μέγιστες ώρες/ημέρα", [8.0, 9.0, 10.0, 12.0], index=2, format_func=lambda v: f"{v:g} ώρες", key="smart_max_hours")
with c4:
    same_region = st.checkbox("Μόνο ίδια περιοχή (όπου είναι γνωστή)", value=False, key="smart_same_region")

vacancies = empty_shifts(st.session_state.assignments, selected_date)
st.caption(f"Βρέθηκαν **{len(vacancies)}** ακάλυπτες θέσεις για {selected_date:%d/%m/%Y}. Κάθε κενή θέση αντιστοιχεί σε μία πραγματική εγγραφή βάρδιας.")

if vacancies:
    selected_id = st.selectbox(
        "Επέλεξε την ακάλυπτη βάρδια",
        [str(a["id"]) for a in vacancies],
        format_func=lambda x: shift_label(next(a for a in vacancies if str(a["id"]) == x)),
        key="smart_selected_vacancy",
    )
    target = next(a for a in vacancies if str(a["id"]) == str(selected_id))
    proj = lookup_name(st.session_state.projects, target.get("projectId"), "Άγνωστο έργο")
    area = region_for_project(target.get("projectId"))
    st.info(
        f"**Επιλεγμένη βάρδια:** {proj} · {selected_date:%d/%m/%Y} · "
        f"{str(target.get('startTime'))[:5]}–{str(target.get('endTime'))[:5]} · "
        f"Περιοχή: {area or 'δεν έχει καταχωρηθεί'}"
    )

    options = {
        "only_external": only_external,
        "travel_buffer_minutes": travel_buffer,
        "maximum_day_hours": max_day_hours,
        "require_same_region": same_region,
    }
    eligible, blocked = rank_candidates(
        target,
        st.session_state.employees,
        st.session_state.assignments,
        st.session_state.leaves,
        area,
        only_external=only_external,
        travel_buffer_minutes=travel_buffer,
        maximum_day_hours=max_day_hours,
        require_same_region=same_region,
        today=local_today(),
    )
    st.markdown(f"#### ✅ Προτεινόμενοι εργαζόμενοι ({len(eligible)})")
    if eligible:
        display = pd.DataFrame([
            {
                "Εργαζόμενος": r["name"],
                "Βαθμολογία": r["score"],
                "Προηγ. ημέρες στο έργο": r["experience_days"],
                "Ώρες σήμερα": r["day_hours"],
                "Ώρες με νέα βάρδια": r["projected_hours"],
                "Περιοχή": r["region"] or "—",
                "Άλλες βάρδιες": r["existing_shifts"],
                "Αιτιολόγηση": r["reason"],
            }
            for r in eligible
        ])
        st.dataframe(display, hide_index=True, use_container_width=True)
        chosen_employee_id = st.selectbox(
            "Εργαζόμενος για την αντικατάσταση",
            [r["employee_id"] for r in eligible],
            format_func=lambda eid: next(
                f"{r['name']} · {r['score']} βαθμοί · {r['projected_hours']:g} ώρες ημέρας"
                for r in eligible if r["employee_id"] == eid
            ),
            key=f"smart_select_emp_{selected_id}",
        )
        chosen_emp = next(e for e in st.session_state.employees if str(e.get("id")) == chosen_employee_id)
        with st.form(f"smart_assign_form_{selected_id}"):
            confirm = st.checkbox("Επιβεβαιώνω ότι θέλω να αναθέσω αυτή τη βάρδια στον επιλεγμένο εργαζόμενο.")
            pressed = st.form_submit_button(
                "✅ Αποθήκευση αντικατάστασης στη Supabase",
                disabled=not utils.supabase or st.session_state.get("current_user") == "TAN",
                use_container_width=True,
            )
        if pressed:
            if not confirm:
                st.warning("Επίλεξε πρώτα την επιβεβαίωση.")
            else:
                assign_replacement(target, chosen_emp, options)
    else:
        st.warning("Δεν βρέθηκαν διαθέσιμοι εργαζόμενοι με αυτά τα κριτήρια. Δοκίμασε διαφορετικό όριο ωρών ή χρόνο μετακίνησης.")

    with st.expander(f"🚫 Εργαζόμενοι που αποκλείστηκαν ({len(blocked)})"):
        if blocked:
            st.dataframe(
                pd.DataFrame([{
                    "Εργαζόμενος": r["name"],
                    "Αιτία": r["reason"],
                    "Ήδη ώρες": r["day_hours"],
                } for r in blocked]),
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("Κανένας αποκλεισμός.")
else:
    st.info("Δεν υπάρχουν ακάλυπτες μη ακυρωμένες βάρδιες για την επιλεγμένη ημέρα.")

st.divider()
with st.expander("📍 Ρυθμίσεις περιοχών εργαζομένων και έργων (προαιρετικό)"):
    st.caption(
        "Οι περιοχές δεν υπάρχουν στο αρχικό μοντέλο του STAFF.PRO. "
        "Για να τις αποθηκεύεις μόνιμα, εκτέλεσε πρώτα το SQL που συνοδεύει την εγκατάσταση. "
        "Η περιοχή δεν υποκαθιστά έλεγχο πραγματικής απόστασης ή χρόνου μετακίνησης."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Περιοχή εργαζομένου**")
        if st.session_state.employees:
            worker_id = st.selectbox(
                "Επιλογή εργαζομένου",
                [str(e["id"]) for e in st.session_state.employees],
                format_func=lambda x: lookup_name(st.session_state.employees, x),
                key="smart_region_emp_select",
            )
            person = next(e for e in st.session_state.employees if str(e.get("id")) == worker_id)
            emp_region = st.text_input(
                "Περιοχή βάσης/διαθεσιμότητας",
                value=str(person.get("region") or ""),
                key=f"smart_region_emp_{worker_id}",
                placeholder="π.χ. Καλαμαριά",
            )
            if st.button("Αποθήκευση περιοχής εργαζομένου", key="smart_emp_region_save"):
                update_region("employees", worker_id, emp_region)
    with right:
        st.markdown("**Περιοχή έργου**")
        if st.session_state.projects:
            proj_id = st.selectbox(
                "Επιλογή έργου",
                [str(p["id"]) for p in st.session_state.projects],
                format_func=lambda x: lookup_name(st.session_state.projects, x),
                key="smart_region_project_select",
            )
            project = next(p for p in st.session_state.projects if str(p.get("id")) == proj_id)
            proj_region = st.text_input(
                "Περιοχή εγκατάστασης",
                value=str(project.get("region") or ""),
                key=f"smart_region_project_{proj_id}",
                placeholder="π.χ. Πυλαία",
            )
            if st.button("Αποθήκευση περιοχής έργου", key="smart_proj_region_save"):
                update_region("projects", proj_id, proj_region)

st.caption(
    "Η κατάταξη είναι συμβουλευτική και όχι αυτόματη απόφαση. "
    "Οι συγκρούσεις αποκλείονται αυστηρά, ακόμη κι αν το Gantt επιτρέπει ειδική εμφάνιση «ΜΕΤΑ ΑΠΟ». "
    "Το όριο ωρών είναι επιχειρησιακό φίλτρο και δεν πιστοποιεί εργατική νομοθεσία. "
    "Για ταυτόχρονες αλλαγές διαφορετικών βαρδιών από πολλούς χρήστες απαιτείται επιπλέον server-side έλεγχος συναλλαγών."
)
