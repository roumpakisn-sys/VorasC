import threading
import uuid
from datetime import datetime

import streamlit as st


def cleanup_duplicates():
    """Ο Σιωπηλός Καθαριστής: Εξολοθρεύει τα 'Φαντάσματα' με 100% ασφάλεια τύπων."""
    import utils

    if not st.session_state.get('assignments'):
        return

    seen_signatures = set()
    duplicates_to_kill = []
    clean_assignments = []

    for a in st.session_state.get('assignments', []):
        if not isinstance(a, dict):
            continue

        sig = (
            str(a.get('date', '')),
            str(a.get('projectId', '')),
            str(a.get('employeeId', '')),
            str(a.get('startTime', ''))[:5] if a.get('startTime') else "",
            str(a.get('endTime', ''))[:5] if a.get('endTime') else "",
            str(a.get('notes', '')),
        )

        if sig in seen_signatures:
            duplicates_to_kill.append(a)
        else:
            seen_signatures.add(sig)
            clean_assignments.append(a)

    if duplicates_to_kill:
        st.session_state.assignments = clean_assignments
        st.session_state.data_dirty = True
        dup_ids = [d['id'] for d in duplicates_to_kill if d.get('id')]

        if utils.supabase and dup_ids:
            def delete_ghosts():
                chunk_size = 100
                for i in range(0, len(dup_ids), chunk_size):
                    chunk = dup_ids[i:i + chunk_size]
                    try:
                        utils.supabase.table('assignments').delete().in_('id', chunk).execute()
                        for rec_id in chunk:
                            utils.track_deletion('assignments', rec_id)
                    except Exception:
                        pass

                try:
                    now_utc = datetime.utcnow().isoformat() + "Z"
                    log_entry = {
                        "id": str(uuid.uuid4()),
                        "timestamp": now_utc,
                        "username": "Σύστημα (Καθαριστής)",
                        "action_type": "ΕΚΚΑΘΑΡΙΣΗ",
                        "table_name": "assignments",
                        "details": f"Διαγράφηκαν {len(dup_ids)} διπλότυπες βάρδιες",
                    }
                    utils.supabase.table("activity_logs").insert(log_entry).execute()
                except Exception:
                    pass

            threading.Thread(target=delete_ghosts, daemon=True).start()


def cleanup_projects():
    """Συγχωνεύει τα διπλά έργα με προστασία από None."""
    import utils

    if not st.session_state.get('projects'):
        return

    name_map = {}
    projects_to_kill = []
    projects_to_keep = []
    id_remap = {}

    for p in st.session_state.get('projects', []):
        if not isinstance(p, dict):
            continue

        name_lower = str(p.get('name') or '').strip().lower()

        if not name_lower:
            projects_to_keep.append(p)
            continue

        if name_lower in name_map:
            keep_id = name_map[name_lower]
            projects_to_kill.append(p)
            pid = p.get('id')
            if pid:
                id_remap[pid] = keep_id
        else:
            pid = p.get('id')
            if pid:
                name_map[name_lower] = pid
            projects_to_keep.append(p)

    if projects_to_kill:
        st.session_state.projects = projects_to_keep

        assignments_to_update = []
        for a in st.session_state.get('assignments', []):
            if isinstance(a, dict) and a.get('projectId') in id_remap:
                a['projectId'] = id_remap[a['projectId']]
                assignments_to_update.append(a)

        patterns_to_update = []
        for pat in st.session_state.get('recurring_patterns', []):
            if isinstance(pat, dict) and pat.get('projectId') in id_remap:
                pat['projectId'] = id_remap[pat['projectId']]
                patterns_to_update.append(pat)

        st.session_state.data_dirty = True

        if utils.supabase:
            def merge_db():
                for a in assignments_to_update:
                    if a.get('id'):
                        try:
                            utils.supabase.table('assignments').update({'projectId': a['projectId']}).eq('id', a['id']).execute()
                        except Exception:
                            pass

                for pat in patterns_to_update:
                    if pat.get('id'):
                        try:
                            utils.supabase.table('recurring_patterns').update({'projectId': pat['projectId']}).eq('id', pat['id']).execute()
                        except Exception:
                            pass

                chunk_size = 100
                del_ids = [p['id'] for p in projects_to_kill if p.get('id')]
                for i in range(0, len(del_ids), chunk_size):
                    try:
                        chunk = del_ids[i:i + chunk_size]
                        utils.supabase.table('projects').delete().in_('id', chunk).execute()
                        for rec_id in chunk:
                            utils.track_deletion('projects', rec_id)
                    except Exception:
                        pass

                try:
                    now_utc = datetime.utcnow().isoformat() + "Z"
                    log_entry = {
                        "id": str(uuid.uuid4()),
                        "timestamp": now_utc,
                        "username": "Σύστημα (Καθαριστής)",
                        "action_type": "ΕΚΚΑΘΑΡΙΣΗ",
                        "table_name": "projects",
                        "details": f"Συγχωνεύτηκαν {len(projects_to_kill)} διπλότυπα έργα",
                    }
                    utils.supabase.table("activity_logs").insert(log_entry).execute()
                except Exception:
                    pass

            threading.Thread(target=merge_db, daemon=True).start()
