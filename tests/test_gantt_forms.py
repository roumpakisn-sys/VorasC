"""Inline Gantt editing stays functional after removing the optional drawer."""
from datetime import time
from pathlib import Path
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class InlineFormTests(unittest.TestCase):
    def app(self, view="desktop"):
        app = AppTest.from_file(str(ROOT / "tests/fixtures/gantt_forms_app.py"))
        app.session_state["fixture_headless"] = True
        # Stale session preferences from the removed feature must not revive it.
        app.session_state["gantt_side_editor_enabled"] = True
        app.run()
        if view == "mobile":
            next(s for s in app.selectbox if s.label == "Έκδοση").set_value(view).run()
        key = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
        app.selectbox(key=key).set_value("bar-a").run()
        self.assertFalse(app.exception)
        return app, key

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def test_inline_save_keeps_both_workers_and_optional_contacts(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app, _ = self.app(view)
                self.assertEqual(len(app.toggle), 0)
                self.assertFalse(any("Κλείσιμο" in b.label or "Προεπισκόπηση" in b.label for b in app.button))
                self.assertTrue(any(t.label == "Οδηγός μεταφοράς" for t in app.text_input))
                self.assertTrue(any(t.label == "Επόπτης" for t in app.text_input))
                app.time_input[-1].set_value(time(13))
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                call, = app.session_state.save_calls
                self.assertTrue(call["keep_worker_ids"])
                self.assertEqual({r["employeeId"] for r in call["new"]}, {"e1", "e2"})
                self.assertTrue(all(r["endTime"] == "13:00" for r in call["new"]))

    def test_invalid_time_and_failed_save_keep_originals(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app, _ = self.app(view)
                app.time_input[-1].set_value(time(8))
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.save_calls, [])
                self.assertTrue(app.error)
                app.checkbox(key="fail_save").set_value(True).run()
                app.time_input[-1].set_value(time(13))
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.time_input[-1].value, time(13))
                self.assertTrue(app.error)
                self.assertEqual(len(app.session_state.assignments), 4)

    def test_dropdown_can_change_and_clear_the_selected_bar(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app, key = self.app(view)
                app.selectbox(key=key).set_value("bar-b").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.time_input[-2].value, time(14))
                self.assertEqual(app.time_input[-1].value, time(16))
                app.selectbox(key=key).set_value("").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.save_calls, [])
                self.assertFalse(any(b.label == "💾 Αποθήκευση" for b in app.button))
