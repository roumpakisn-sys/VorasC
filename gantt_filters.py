import hashlib

import streamlit as st


PREFERENCE_KEY = "gantt_hidden_recurring_project_ids"


def _project_name(project_id, projects):
    for project in projects or []:
        if isinstance(project, dict) and project.get("id") == project_id:
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


def _checkbox_key(project_id):
    digest = hashlib.md5(str(project_id).encode("utf-8")).hexdigest()
    return f"gantt_recurring_project_visible_{digest}"


def _known_projects_key():
    return "gantt_known_recurring_project_ids"


def _hidden_projects_key():
    return "gantt_hidden_recurring_project_ids"


def _visible_projects_key():
    return "gantt_visible_recurring_project_ids"


def _loaded_user_key():
    return "gantt_recurring_filter_loaded_for_user"


def _normalize_project_list(values, allowed_ids):
    allowed = set(allowed_ids or [])
    clean = []

    for value in values or []:
        if value in allowed and value not in clean:
            clean.append(value)

    return clean


def _current_username():
    return st.session_state.get("current_user") or ""


def _load_hidden_projects_from_db(recurring_project_ids):
    """
    Φορτώνει από Supabase τις κρυμμένες επιλογές του τρέχοντος χρήστη.
    Αν δεν υπάρχει πίνακας/σύνδεση, η εφαρμογή συνεχίζει με session state.
    """
    username = _current_username()
    if not username:
        return None

    try:
        import utils

        if not utils.supabase:
            return None

        res = (
            utils.supabase
            .table("user_preferences")
            .select("preference_value")
            .eq("username", username)
            .eq("preference_key", PREFERENCE_KEY)
            .limit(1)
            .execute()
        )

        rows = res.data or []
        if not rows:
            return []

        value = rows[0].get("preference_value")
        if not isinstance(value, list):
            return []

        return _normalize_project_list(value, recurring_project_ids)

    except Exception as e:
        print(f"Could not load Gantt recurring filter preference: {e}")
        return None


def _save_hidden_projects_to_db(hidden_project_ids):
    """
    Αποθηκεύει στη Supabase τις κρυμμένες επιλογές του τρέχοντος χρήστη.
    Είναι σιωπηλό ώστε να μην κρασάρει το Gantt αν η βάση δεν έχει ακόμα τον πίνακα.
    """
    username = _current_username()
    if not username:
        return

    try:
        import utils

        if not utils.supabase:
            return

        payload = {
            "username": username,
            "preference_key": PREFERENCE_KEY,
            "preference_value": list(hidden_project_ids or []),
        }

        (
            utils.supabase
            .table("user_preferences")
            .upsert(payload, on_conflict="username,preference_key")
            .execute()
        )

    except Exception as e:
        print(f"Could not save Gantt recurring filter preference: {e}")


def _load_user_preferences_once(recurring_project_ids):
    """
    Φορτώνει τις επιλογές μόνο μία φορά ανά χρήστη/session.

    Επιστρέφει True μόνο όταν μόλις έγινε φόρτωση από τη βάση.
    Αυτό είναι κρίσιμο: αν ξαναγράφουμε τα checkbox σε κάθε rerun,
    τότε όταν ο χρήστης ξανατικάρει ένα κρυμμένο έργο, το παλιό hidden state
    το ξετικάρει ξανά.
    """
    username = _current_username()
    loaded_key = _loaded_user_key()
    hidden_key = _hidden_projects_key()

    if st.session_state.get(loaded_key) == username:
        return False

    db_hidden_ids = _load_hidden_projects_from_db(recurring_project_ids)
    if db_hidden_ids is not None:
        st.session_state[hidden_key] = db_hidden_ids
    else:
        st.session_state[hidden_key] = _normalize_project_list(
            st.session_state.get(hidden_key, []),
            recurring_project_ids,
        )

    st.session_state[loaded_key] = username
    return True


def _prepare_state(recurring_project_ids):
    """
    Η σταθερή μνήμη του φίλτρου είναι η λίστα κρυμμένων recurring project ids.
    Πλέον φορτώνεται και αποθηκεύεται ανά χρήστη στη Supabase.

    Η βάση εφαρμόζεται στα checkbox μόνο όταν μπαίνει/φορτώνει ο χρήστης.
    Μετά από αυτό, η αλήθεια είναι το ίδιο το checkbox.
    """
    known_key = _known_projects_key()
    hidden_key = _hidden_projects_key()

    loaded_from_db_now = _load_user_preferences_once(recurring_project_ids)

    previous_known = st.session_state.get(known_key)
    if previous_known is None:
        previous_known = []

    hidden_ids = _normalize_project_list(
        st.session_state.get(hidden_key, []),
        recurring_project_ids,
    )

    st.session_state[hidden_key] = hidden_ids
    st.session_state[known_key] = list(recurring_project_ids)

    for project_id in recurring_project_ids:
        cb_key = _checkbox_key(project_id)

        if cb_key not in st.session_state:
            st.session_state[cb_key] = project_id not in hidden_ids
        elif loaded_from_db_now:
            # Μόνο στην πρώτη φόρτωση χρήστη συγχρονίζουμε widget από τη μόνιμη προτίμηση.
            st.session_state[cb_key] = project_id not in hidden_ids

    # Καθαρισμός παλιών checkbox keys για έργα που δεν είναι πια recurring.
    current_checkbox_keys = {_checkbox_key(pid) for pid in recurring_project_ids}
    for old_project_id in previous_known:
        old_key = _checkbox_key(old_project_id)
        if old_key not in current_checkbox_keys:
            st.session_state.pop(old_key, None)


def _sync_hidden_from_checkboxes(recurring_project_ids, save=True):
    hidden_ids = []

    for project_id in recurring_project_ids:
        is_visible = bool(st.session_state.get(_checkbox_key(project_id), True))
        if not is_visible:
            hidden_ids.append(project_id)

    hidden_ids = _normalize_project_list(hidden_ids, recurring_project_ids)
    st.session_state[_hidden_projects_key()] = hidden_ids

    visible_ids = [
        project_id
        for project_id in recurring_project_ids
        if project_id not in hidden_ids
    ]

    st.session_state[_visible_projects_key()] = visible_ids

    if save:
        _save_hidden_projects_to_db(hidden_ids)

    return visible_ids


def render_recurring_project_visibility_filter(projects, recurring_patterns, on_change=None):
    """
    Sidebar φίλτρο για το ποια έργα από επαναλαμβανόμενες εργασίες
    θα εμφανίζονται στο Gantt.

    Επιστρέφει λίστα με project ids που πρέπει να εμφανίζονται.
    Δεν αλλάζει δεδομένα στη βάση και δεν πειράζει τις επαναλαμβανόμενες εργασίες.
    """
    recurring_project_ids = _get_recurring_project_ids(projects, recurring_patterns)

    if not recurring_project_ids:
        st.session_state[_hidden_projects_key()] = []
        st.session_state[_visible_projects_key()] = []
        st.session_state[_known_projects_key()] = []
        return []

    _prepare_state(recurring_project_ids)

    with st.sidebar.expander("👁️ Εμφάνιση επαναλαμβανόμενων στο Gantt", expanded=False):
        st.caption("Τικάρετε ποια έργα από επαναλαμβανόμενες εργασίες θα φαίνονται στο διάγραμμα.")

        c1, c2 = st.columns(2)

        with c1:
            if st.button("Όλα", key="show_all_recurring_projects", use_container_width=True):
                for project_id in recurring_project_ids:
                    st.session_state[_checkbox_key(project_id)] = True

                st.session_state[_hidden_projects_key()] = []
                st.session_state[_visible_projects_key()] = list(recurring_project_ids)
                _save_hidden_projects_to_db([])

                if on_change:
                    on_change()

                st.rerun()

        with c2:
            if st.button("Κανένα", key="hide_all_recurring_projects", use_container_width=True):
                for project_id in recurring_project_ids:
                    st.session_state[_checkbox_key(project_id)] = False

                hidden_ids = list(recurring_project_ids)
                st.session_state[_hidden_projects_key()] = hidden_ids
                st.session_state[_visible_projects_key()] = []
                _save_hidden_projects_to_db(hidden_ids)

                if on_change:
                    on_change()

                st.rerun()

        for project_id in recurring_project_ids:
            st.checkbox(
                _project_name(project_id, projects),
                key=_checkbox_key(project_id),
                on_change=on_change,
            )

        visible_ids = _sync_hidden_from_checkboxes(recurring_project_ids, save=True)

        hidden_count = len(recurring_project_ids) - len(visible_ids)
        if hidden_count > 0:
            st.caption(f"Κρυμμένα επαναλαμβανόμενα έργα: {hidden_count}")
        else:
            st.caption("Εμφανίζονται όλα τα επαναλαμβανόμενα έργα.")

    visible_ids = _sync_hidden_from_checkboxes(recurring_project_ids, save=True)
    return visible_ids


def apply_recurring_project_visibility_filter(assignments_by_date, visible_project_ids):
    """
    Επιστρέφει νέο assignments_by_date μόνο για προβολή στο Gantt.

    Κρύβει έργα που ανήκουν στη λίστα recurring patterns και είναι ξετικαρισμένα.
    Αυτό είναι πιο ασφαλές από το να βασιζόμαστε μόνο στο assignment.recurring_id.
    """
    visible_project_ids = set(visible_project_ids or [])
    recurring_project_ids = set(st.session_state.get(_known_projects_key(), []))

    filtered = {}

    for day, assignments in (assignments_by_date or {}).items():
        kept = []

        for assignment in assignments or []:
            if not isinstance(assignment, dict):
                continue

            project_id = assignment.get("projectId")

            if project_id in recurring_project_ids and project_id not in visible_project_ids:
                continue

            kept.append(assignment)

        filtered[day] = kept

    return filtered


def get_recurring_filter_version(visible_project_ids):
    """Σταθερό μικρό hash για να σπάει σωστά το st.cache_data όταν αλλάζει το φίλτρο."""
    hidden = st.session_state.get(_hidden_projects_key(), [])
    joined = "|".join(sorted(visible_project_ids or [])) + "::hidden::" + "|".join(sorted(hidden or []))
    return hashlib.md5(joined.encode("utf-8")).hexdigest()
