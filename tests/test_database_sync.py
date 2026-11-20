from contextlib import redirect_stdout
from datetime import date
import importlib.util
import io
from pathlib import Path
import sys
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_ui_storage import State


class IncrementalSyncTests(unittest.TestCase):
    def load(self, responses):
        state = State(last_sync_time="old", assignments=[{"id": "removed"}], employees=[])
        barrier = Barrier(6, timeout=3)

        def table(name):
            query = Mock()
            if name == "deleted_records":
                query.select.return_value.gte.return_value.execute.return_value.data = [
                    {"table_name": "assignments", "record_id": "removed"}
                ]
            else:
                def execute():
                    barrier.wait()
                    value = responses.get(name, [])
                    if isinstance(value, Exception):
                        raise value
                    return SimpleNamespace(data=value)

                query.select.return_value.gte.return_value.execute.side_effect = execute
            return query

        helpers = SimpleNamespace(
            supabase=SimpleNamespace(table=table), safe_date_parse=date.fromisoformat,
            mark_data_changed=Mock(),
        )
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("db_sync_test", root / "database.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"streamlit": SimpleNamespace(session_state=state), "utils": helpers}):
            spec.loader.exec_module(module)
        self.addCleanup(module._sync_reads.shutdown)
        module.get_db_current_time = lambda: "new"
        return module, state, helpers.mark_data_changed

    def test_table_reads_run_in_parallel_and_preserve_updates_and_deletions(self):
        module, state, changed = self.load({"assignments": [{"id": "added", "date": "2026-11-20"}]})
        module.sync_data_incremental(silent=True)
        self.assertEqual(state.assignments, [{"id": "added", "date": date(2026, 11, 20)}])
        self.assertEqual(state.last_sync_time, "new")
        changed.assert_called_once()

    def test_failed_read_keeps_existing_snapshot_and_cursor(self):
        module, state, changed = self.load({
            "employees": [{"id": "new"}], "evaluations": RuntimeError("network down"),
        })
        with redirect_stdout(io.StringIO()):
            module.sync_data_incremental(silent=True)
        self.assertEqual(state.employees, [])
        self.assertEqual(state.assignments, [{"id": "removed"}])
        self.assertEqual(state.last_sync_time, "old")
        changed.assert_not_called()
