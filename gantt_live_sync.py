"""Check for saved changes without interrupting Gantt editing."""
from datetime import datetime, timezone


def _parse_timestamp(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def pending_revision(client, synced_through):
    """Read the small change marker through the app's server-side DB client."""
    synced = _parse_timestamp(synced_through)
    if client is None or synced is None:
        return None
    try:
        rows = (
            client.table("app_sync_state")
            .select("last_changed_at")
            .eq("id", "global")
            .limit(1)
            .execute()
            .data
        )
        changed_at = _parse_timestamp(rows[0].get("last_changed_at")) if rows else None
    except Exception:
        return None
    return changed_at if changed_at and changed_at > synced else None


def render_update_check(client, *, live_view):
    import streamlit as st

    if client is None:
        return

    @st.fragment(run_every=30)
    def check_for_updates():
        state = st.session_state
        revision = pending_revision(client, state.get("last_sync_time"))
        if revision is None:
            return
        if live_view and revision != state.get("gantt_live_sync_requested"):
            # Attempt each revision once. A failed sync must not cause a rerun loop.
            state["gantt_live_sync_requested"] = revision
            state.pop("skip_remote_sync_once", None)
            st.rerun()
        st.caption("Υπάρχουν νεότερες αλλαγές στο πρόγραμμα.")
        if st.button("Ενημέρωση προγράμματος", key="gantt_live_sync_refresh"):
            state.pop("skip_remote_sync_once", None)
            st.rerun()

    check_for_updates()
