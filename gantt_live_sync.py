"""Receive the server-side Gantt change marker and fall back to a small REST check."""

import asyncio
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic

CHECK_SECONDS = 3
FALLBACK_SECONDS = 30


def _parse_timestamp(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


class ChangeMarker:
    def __init__(self):
        self._lock = Lock()
        self._latest = None
        self._next_check = 0
        self._checking_rest = False
        self._worker = None

    def _remember(self, value):
        revision = _parse_timestamp(value)
        with self._lock:
            if revision is not None and (self._latest is None or revision > self._latest):
                self._latest = revision

    def receive(self, payload):
        record = (payload.get("data") or {}).get("record") or {}
        if record.get("id") == "global":
            self._remember(record.get("last_changed_at"))

    def latest(self, client):
        with self._lock:
            now = monotonic()
            check_rest = not self._checking_rest and now >= self._next_check
            if check_rest:
                self._checking_rest = True
                self._next_check = now + FALLBACK_SECONDS
            if self._worker is None:
                key = getattr(client, "supabase_key", None)
                url = str(getattr(client, "supabase_url", ""))
                if isinstance(key, str) and url.startswith(("https://", "http://")):
                    self._worker = Thread(target=self._listen, args=(url, key), daemon=True)
                    self._worker.start()

        if check_rest:
            Thread(target=self._check_rest, args=(client,), daemon=True).start()

        with self._lock:
            return self._latest

    def _check_rest(self, client):
        try:
            rows = (
                client.table("app_sync_state")
                .select("last_changed_at")
                .eq("id", "global")
                .limit(1)
                .execute()
                .data
            )
            if rows:
                self._remember(rows[0].get("last_changed_at"))
        except Exception:
            pass  # A failed REST check must not hide a received Realtime revision.
        finally:
            with self._lock:
                self._checking_rest = False

    def _listen(self, url, key):
        asyncio.run(self._listen_with_retry(url, key))

    async def _listen_with_retry(self, url, key):
        try:
            from supabase import acreate_client
        except ImportError:
            return  # REST fallback also works with an older SDK.

        while True:
            realtime = None
            try:
                client = await acreate_client(url, key)
                realtime = client.realtime
                if key.startswith(("sb_secret_", "sb_publishable_")):
                    # Opaque keys authenticate the socket via apikey, like the Data API.
                    await realtime.set_auth(None)
                disconnected = asyncio.Event()

                def subscribed(status, _error):
                    if status in ("CHANNEL_ERROR", "TIMED_OUT", "CLOSED"):
                        disconnected.set()

                channel = realtime.channel("gantt-sync").on_postgres_changes(
                    "*", schema="public", table="app_sync_state", filter="id=eq.global",
                    callback=self.receive,
                )
                await asyncio.wait_for(channel.subscribe(subscribed), timeout=FALLBACK_SECONDS)
                while realtime.is_connected and not disconnected.is_set():
                    try:
                        await asyncio.wait_for(disconnected.wait(), timeout=FALLBACK_SECONDS)
                    except TimeoutError:
                        continue
            except Exception:
                pass  # Transport errors are recoverable. Keep the REST check active.
            finally:
                if realtime is not None:
                    await asyncio.gather(realtime.close(), return_exceptions=True)
            await asyncio.sleep(FALLBACK_SECONDS)


_marker = ChangeMarker()


def pending_revision(client, synced_through):
    synced = _parse_timestamp(synced_through)
    if client is None or synced is None:
        return None
    revision = _marker.latest(client)
    return revision if revision and revision > synced else None


def _render_refresh(st):
    st.caption("Υπάρχουν νεότερες αλλαγές στο πρόγραμμα.")
    if st.button("Ενημέρωση προγράμματος", key="gantt_live_sync_refresh"):
        st.session_state.pop("skip_remote_sync_once", None)
        st.rerun()


def render_update_check(client):
    import streamlit as st

    if client is None:
        return

    @st.fragment(run_every=CHECK_SECONDS)
    def check_for_updates():
        if pending_revision(client, st.session_state.get("last_sync_time")):
            _render_refresh(st)

    check_for_updates()


def render_live_view(client, *, build, refresh, can_refresh=None):
    """Refresh the chart fragment without starting an app rerun."""
    import streamlit as st

    snapshot = build(first_render=True)
    attempted_revision = None
    retry_after = 0
    initial_render = True

    @st.fragment(run_every=CHECK_SECONDS if client is not None else None)
    def view():
        nonlocal snapshot, attempted_revision, retry_after, initial_render
        state = st.session_state
        revision = pending_revision(client, state.get("last_sync_time"))
        if initial_render:
            # The page has its own current snapshot, including any confirmed local write.
            # A pending Realtime revision can wait for the first scheduled update.
            initial_render = False
            snapshot()
            return
        if (
            revision
            and (can_refresh is None or can_refresh())
            and (revision != attempted_revision or monotonic() >= retry_after)
        ):
            attempted_revision = revision
            retry_after = monotonic() + FALLBACK_SECONDS
            refresh()
            synced = _parse_timestamp(state.get("last_sync_time"))
            if synced is not None and synced >= revision:
                snapshot = build(first_render=False)
                revision = None

        snapshot()
        if revision:
            _render_refresh(st)

    view()
