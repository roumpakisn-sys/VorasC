import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import gantt_live_sync


class AppRerun(Exception):
    pass


class GanttLiveSyncTests(unittest.TestCase):
    def client(self, changed_at):
        client = Mock()
        query = client.table.return_value.select.return_value.eq.return_value.limit.return_value
        query.execute.return_value.data = [{"last_changed_at": changed_at}]
        return client

    def view(self, synced_through):
        return SimpleNamespace(
            session_state={"last_sync_time": synced_through, "skip_remote_sync_once": True},
            fragment=Mock(side_effect=lambda **_: lambda function: function),
            caption=Mock(),
            button=Mock(return_value=False),
            rerun=Mock(side_effect=AppRerun),
        )

    def test_reader_refreshes_new_revision_once_and_does_not_reload_current_view(self):
        client = self.client("2026-11-19T13:01:01+02:00")
        writer = self.view("2026-11-19T11:01:02Z")
        reader = self.view("2026-11-19T11:00:00Z")
        with patch.dict(sys.modules, streamlit=writer):
            gantt_live_sync.render_update_check(client, live_view=True)
            writer.rerun.assert_not_called()
        with patch.dict(sys.modules, streamlit=reader):
            with self.assertRaises(AppRerun):
                gantt_live_sync.render_update_check(client, live_view=True)
            self.assertNotIn("skip_remote_sync_once", reader.session_state)
            gantt_live_sync.render_update_check(client, live_view=True)
            reader.rerun.assert_called_once()
            reader.button.assert_called_once()
            reader.session_state["last_sync_time"] = writer.session_state["last_sync_time"]
            gantt_live_sync.render_update_check(client, live_view=True)
            reader.button.assert_called_once()

    def test_editor_sees_new_revision_and_refreshes_only_on_request(self):
        client = self.client("2026-11-19T11:01:01Z")
        editor = self.view("2026-11-19T11:00:00")
        with patch.dict(sys.modules, streamlit=editor):
            gantt_live_sync.render_update_check(client, live_view=False)
            editor.rerun.assert_not_called()
            editor.button.assert_called_once()
            editor.button.return_value = True
            with self.assertRaises(AppRerun):
                gantt_live_sync.render_update_check(client, live_view=False)
            self.assertNotIn("skip_remote_sync_once", editor.session_state)
