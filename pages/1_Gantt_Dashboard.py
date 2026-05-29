import hashlib

import streamlit as st


def _project_name(project_id, projects):
    for project in projects or []:
        if project.get("id") == project_id:
            return project.get("name", "Άγνωστο Έργο")
    return "Άγνωστο Έργο"


def _get_recurring_project_ids(projects, recurring_patterns):
    """Επιστρέφει μοναδικά project ids που χρησιμοποιούνται σε επαναλαμβανόμενες εργασίες."""
    project_ids = []
    known_project_ids = {p.get("id") for p in projects or [] if isinstance(p, dict)}

    for pattern in recurring_patterns or []:
        if not isinstance(pattern, dict):
            continue
        project_id = pattern.get("projectId")
        if project_id and project_id in known_project_ids and project_id not in project_ids:
            project_ids.append(project_id)

    project_ids.sort(key=lambda pid: _project_name(pid, projects).lower())
    return project_ids


def render_recurring_project_visibility_filter(projects, recurring_patterns, on_change=None):
    """
    Sidebar φίλτρο για το ποια έργα από επαναλαμβανόμενες εργασίες
    θα εμφανίζονται στο Gantt.

    Επιστρέφει λίστα με project ids που πρέπει να εμφανίζονται.
    Δεν αλλάζει δεδομένα στη βάση και δεν πειράζει τις επαναλαμβανόμενες εργασίες.
    """
    recurring_project_ids = _get_recurring_project_ids(projects, recurring_patterns)
    key = "gantt_visible_recurring_project_ids"

    if not recurring_project_ids:
        st.session_state[key] = []
        return []

    current = st.session_state.get(key)
    if current is None:
        st.session_state[key] = list(recurring_project_ids)
    else:
        # Κρατάμε μόνο ids που συνεχίζουν να υπάρχουν και προσθέτουμε νέα recurring έργα ως ορατά.
        cleaned = [pid for pid in current if pid in recurring_project_ids]
        for pid in recurring_project_ids:
            if pid not in cleaned:
                cleaned.append(pid)
        st.session_state[key] = cleaned

    with st.sidebar.expander("👁️ Εμφάνιση επαναλαμβανόμενων στο Gantt", expanded=False):
        st.caption("Επιλέξτε ποια έργα από τις επαναλαμβανόμενες εργασίες θα φαίνονται στο διάγραμμα.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Όλα", key="show_all_recurring_projects", use_container_width=True):
                st.session_state[key] = list(recurring_project_ids)
                if on_change:
                    on_change()
                st.rerun()
        with c2:
            if st.button("Κανένα", key="hide_all_recurring_projects", use_container_width=True):
                st.session_state[key] = []
                if on_change:
                    on_change()
                st.rerun()

        selected = st.multiselect(
            "Έργα επαναλαμβανόμενων",
            options=recurring_project_ids,
            default=st.session_state[key],
            format_func=lambda pid: _project_name(pid, projects),
            key=key,
            on_change=on_change,
        )

        hidden_count = len(recurring_project_ids) - len(selected)
        if hidden_count > 0:
            st.caption(f"Κρυμμένα επαναλαμβανόμενα έργα: {hidden_count}")
        else:
            st.caption("Εμφανίζονται όλα τα επαναλαμβανόμενα έργα.")

    return list(st.session_state.get(key, []))


def apply_recurring_project_visibility_filter(assignments_by_date, visible_project_ids):
    """
    Επιστρέφει νέο assignments_by_date μόνο για προβολή στο Gantt.
    Κρύβει μόνο assignments με recurring_id και projectId εκτός επιλογής.
    """
    visible_project_ids = set(visible_project_ids or [])
    filtered = {}

    for day, assignments in (assignments_by_date or {}).items():
        kept = []
        for assignment in assignments or []:
            if not isinstance(assignment, dict):
                continue

            is_recurring_assignment = bool(assignment.get("recurring_id"))
            project_id = assignment.get("projectId")

            if is_recurring_assignment and project_id not in visible_project_ids:
                continue

            kept.append(assignment)

        filtered[day] = kept

    return filtered


def get_recurring_filter_version(visible_project_ids):
    """Σταθερό μικρό hash για να σπάει σωστά το st.cache_data όταν αλλάζει το φίλτρο."""
    joined = "|".join(sorted(visible_project_ids or []))
    return hashlib.md5(joined.encode("utf-8")).hexdigest()
