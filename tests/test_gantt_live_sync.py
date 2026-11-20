import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import gantt_live_sync


OLD = "2026-11-19T11:00:00Z"
CHANGED = "2026-11-19T13:01:01+02:00"
CURRENT = "2026-11-19T11:01:02Z"


class AppRerun(Exception):
    pass


class GanttLiveSyncTests(unittest.TestCase):
    def setUp(self):
        self.marker = gantt_live_sync.ChangeMarker()
        marker_patch = patch.object(gantt_live_sync, "_marker", self.marker)
        marker_patch.start()
        self.addCleanup(marker_patch.stop)

    def client(self, changed_at):
        client = Mock()
        self.query = client.table.return_value.select.return_value.eq.return_value.limit.return_value
        self.query.execute.return_value.data = [{"last_changed_at": changed_at}]
        return client

    def view(self, synced_through):
        fragments = []

        def fragment(**_):
            def register(function):
                fragments.append(function)
                return function
            return register

        return SimpleNamespace(
            session_state={"last_sync_time": synced_through, "skip_remote_sync_once": True},
            fragment=fragment,
            fragments=fragments,
            caption=Mock(),
            button=Mock(return_value=False),
            rerun=Mock(side_effect=AppRerun),
        )

    def change(self, stamp=CHANGED, row_id="global"):
        self.marker.receive({"data": {"record": {"id": row_id, "last_changed_at": stamp}}})

    def test_realtime_signal_reaches_sessions_before_next_shared_rest_check(self):
        client = self.client(OLD)
        self.assertIsNone(gantt_live_sync.pending_revision(client, OLD))
        self.change(row_id="other")
        self.assertIsNone(gantt_live_sync.pending_revision(client, OLD))
        self.change()
        self.change(stamp=OLD)
        self.assertIsNotNone(gantt_live_sync.pending_revision(client, OLD))
        self.assertIsNone(gantt_live_sync.pending_revision(client, CURRENT))
        self.query.execute.assert_called_once()

    def test_rest_check_recovers_from_missing_realtime_events(self):
        client = self.client(OLD)
        with patch.object(gantt_live_sync, "monotonic", side_effect=[100, 103, 130]):
            self.assertIsNone(gantt_live_sync.pending_revision(client, OLD))
            self.query.execute.return_value.data = [{"last_changed_at": CHANGED}]
            self.assertIsNone(gantt_live_sync.pending_revision(client, OLD))
            self.assertIsNotNone(gantt_live_sync.pending_revision(client, OLD))
        self.assertEqual(self.query.execute.call_count, 2)

    def test_subscribes_to_sync_row_and_closes_on_channel_error(self):
        realtime = Mock()
        channel = realtime.channel.return_value
        channel.on_postgres_changes.return_value = channel
        realtime.close = AsyncMock()
        realtime.set_auth = AsyncMock()

        async def subscribe(status):
            self.change()
            status("CHANNEL_ERROR", None)

        channel.subscribe = AsyncMock(side_effect=subscribe)
        factory = AsyncMock(return_value=SimpleNamespace(realtime=realtime))
        with patch.dict(sys.modules, supabase=SimpleNamespace(acreate_client=factory)):
            with patch.object(gantt_live_sync.asyncio, "sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(self.marker._listen_with_retry("https://example.test", "sb_secret_test"))
        channel.on_postgres_changes.assert_called_once_with(
            "*", schema="public", table="app_sync_state", filter="id=eq.global",
            callback=self.marker.receive,
        )
        realtime.set_auth.assert_awaited_once_with(None)
        realtime.close.assert_awaited_once()

    def test_viewer_rebuilds_snapshot_once_without_reloading_page(self):
        client = self.client(OLD)
        viewer = self.view(OLD)
        before, after = Mock(), Mock()
        build = Mock(side_effect=[before, after])

        def refresh():
            viewer.session_state["last_sync_time"] = CURRENT

        with patch.dict(sys.modules, streamlit=viewer):
            gantt_live_sync.render_live_view(client, build=build, refresh=refresh)
            self.change()
            viewer.fragments[0]()
            viewer.fragments[0]()
        self.assertEqual(build.call_count, 2)
        before.assert_called_once()
        self.assertEqual(after.call_count, 2)
        viewer.rerun.assert_not_called()
        viewer.button.assert_not_called()

    def test_failed_viewer_update_preserves_chart_and_offers_refresh(self):
        client = self.client(CHANGED)
        viewer = self.view(OLD)
        chart = Mock()
        build = Mock(return_value=chart)
        refresh = Mock()
        with patch.dict(sys.modules, streamlit=viewer):
            gantt_live_sync.render_live_view(client, build=build, refresh=refresh)
            viewer.fragments[0]()
        build.assert_called_once_with(first_render=True)
        refresh.assert_called_once()
        self.assertEqual(chart.call_count, 2)
        viewer.rerun.assert_not_called()
        self.assertEqual(viewer.button.call_count, 2)

    def test_editor_keeps_selected_bar_then_applies_pending_revision_when_idle(self):
        client = self.client(OLD)
        editor = self.view(OLD)
        editor.session_state["selected_bar"] = "bar-a"
        before, after = Mock(), Mock()
        build = Mock(side_effect=[before, after])
        refresh = Mock(side_effect=lambda: editor.session_state.update(last_sync_time=CURRENT))

        with patch.dict(sys.modules, streamlit=editor):
            gantt_live_sync.render_live_view(
                client, build=build, refresh=refresh,
                can_refresh=lambda: not editor.session_state.get("selected_bar"),
            )
            self.change()
            editor.fragments[0]()
            refresh.assert_not_called()
            self.assertEqual(editor.button.call_count, 1)
            self.assertEqual(before.call_count, 2)

            editor.session_state.pop("selected_bar")
            editor.fragments[0]()
            editor.fragments[0]()

        refresh.assert_called_once()
        self.assertEqual(after.call_count, 2)
        editor.rerun.assert_not_called()
        self.assertEqual(editor.button.call_count, 1)

    def test_manual_mode_refreshes_only_on_request(self):
        client = self.client(CHANGED)
        editor = self.view(OLD)
        with patch.dict(sys.modules, streamlit=editor):
            gantt_live_sync.render_update_check(client)
            editor.rerun.assert_not_called()
            editor.button.assert_called_once()
            editor.button.return_value = True
            with self.assertRaises(AppRerun):
                editor.fragments[0]()
            self.assertNotIn("skip_remote_sync_once", editor.session_state)
