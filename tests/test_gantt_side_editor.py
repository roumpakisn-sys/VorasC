from datetime import date, time
from pathlib import Path
import unittest
from unittest.mock import patch

import gantt_side_editor as editor

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


class PreviewTests(unittest.TestCase):
    def test_kill_switch(self):
        self.assertTrue(editor.feature_available({}))
        for value in ("0", "false", "OFF", " no "):
            self.assertFalse(editor.feature_available({"STAFFPRO_SIDE_EDITOR_ENABLED": value}))

    def test_disabled_wrapper_does_not_load_streamlit_or_call_close(self):
        with patch.dict('sys.modules', {'streamlit': None}):
            with editor.editor(False, "bar", page="desktop", on_close=lambda: self.fail("closed")):
                pass

    def test_preview_retains_all_workers_and_reports_only_changes(self):
        original = editor.summary(day=date(2026, 11, 16), project="Έργο", employees=["Β", "Α"],
            arrival="", start="09:00", end="12:00", color="Πράσινο", notes="",
            general=False, cancelled=False, reason="")
        draft = {**original, "Λήξη": "13:00"}
        self.assertEqual(original["Προσωπικό"], "Α, Β")
        self.assertEqual(editor.changes(original, draft), [
            {"Πεδίο": "Λήξη", "Πριν": "12:00", "Μετά": "13:00"}])
        self.assertEqual(original["Λήξη"], "12:00")


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class RealFormTests(unittest.TestCase):
    def app(self, view="desktop", enabled=True):
        app = AppTest.from_file(str(Path(__file__).parent / "fixtures" / "side_editor_app.py"))
        app.session_state["fixture_headless"] = True
        app.run()
        if view == "mobile":
            next(s for s in app.selectbox if s.label == "Έκδοση").set_value(view).run()
        if enabled:
            app.toggle[0].set_value(True).run()
        select = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
        app.selectbox(key=select).set_value("bar-a").run()
        self.assertFalse(app.exception)
        return app

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def test_off_preserves_original_controls_and_save(self):
        app = self.app(enabled=False)
        self.assertFalse(any("Κλείσιμο" in b.label or "Προεπισκόπηση" in b.label for b in app.button))
        next(t for t in app.time_input if t.label == "Νέα Λήξη").set_value(time(13))
        self.button(app, "💾 Αποθήκευση").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.save_calls), 1)
        self.assertEqual([r['endTime'] for r in app.session_state.save_calls[0]['new']], ['13:00', '13:00'])

    def test_preview_never_saves_and_close_never_saves(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                app.time_input[-1].set_value(time(13))
                self.button(app, "🔎 Προεπισκόπηση αλλαγών").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.save_calls, [])
                self.assertEqual(app.table[0].value.iloc[0]["Μετά"], "13:00")
                self.button(app, "✕ Κλείσιμο επεξεργασίας").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.save_calls, [])
                self.assertEqual(len(app.time_input), 0)

    def test_enabled_save_keeps_same_atomic_api_and_both_workers(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                app.time_input[-1].set_value(time(13))
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                call = app.session_state.save_calls[0]
                self.assertTrue(call['keep_worker_ids'])
                self.assertEqual({r['id'] for r in call['old']}, {'bar-a-1', 'bar-a-2'})
                self.assertEqual({r['employeeId'] for r in call['new']}, {'e1', 'e2'})
                self.assertTrue(all(r['endTime'] == '13:00' for r in call['new']))

    def test_validation_and_save_failure_keep_form_and_draft(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
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

    def test_next_bar_loads_its_own_times_and_notes(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                app.time_input[-1].set_value(time(13))
                self.button(app, "🔎 Προεπισκόπηση αλλαγών").click().run()
                select = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
                app.selectbox(key=select).set_value("bar-b").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.time_input[-1].value, time(16))
                self.assertEqual(app.time_input[-2].value, time(14))
                self.assertEqual(app.session_state.save_calls, [])

    def test_toggle_off_removes_drawer_and_preview(self):
        app = self.app()
        app.toggle[0].set_value(False).run()
        self.assertFalse(app.exception)
        self.assertFalse(any("Κλείσιμο" in b.label or "Προεπισκόπηση" in b.label for b in app.button))
        self.assertTrue(any(b.label == "💾 Αποθήκευση" for b in app.button))

    def test_global_disable_hides_switch_even_if_session_was_enabled(self):
        app = self.app()
        with patch.dict('os.environ', {"STAFFPRO_SIDE_EDITOR_ENABLED": "0"}):
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.toggle), 0)
        self.assertFalse(any("Κλείσιμο" in b.label for b in app.button))
