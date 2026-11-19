from datetime import date
import unittest

import placement_text


class PlacementTextTests(unittest.TestCase):
    today = date(2026, 11, 19)
    projects = [{"id": "p1", "name": "ISOMAT"}, {"id": "p2", "name": "ISOMAT Αποθήκη"}]
    people = [
        {"id": "e1", "name": "ΜΑΡΙΑ ΠΑΠΠΑ"},
        {"id": "e2", "name": "ΝΙΚΟΛΑΟΥ ΓΙΑΝΝΗΣ"},
        {"id": "e3", "name": "Κώστας Πέτρου"},
        {"id": "e4", "name": "Μαρία Ιωάννου"},
    ]

    def parse(self, message):
        return placement_text.parse(message, self.projects, self.people, self.today)

    def test_viber_style_placement_keeps_roles_separate_from_crew(self):
        values, warnings = self.parse(
            "Μαρία Παππά και Γιάννης Νικολάου στο ISOMAT Παρασκευή 20/11, 7 με 11 το πρωί, "
            "ΒΙΠΕ Σίνδου. Τους πάει ο Κώστας, επιστροφή με τον Νίκο. Επόπτρια η Ελένη."
        )
        self.assertFalse(warnings)
        self.assertEqual(values["project_id"], "p1")
        self.assertEqual(values["first_date"], date(2026, 11, 20))
        self.assertEqual((values["start_time"], values["end_time"]), ("07:00", "11:00"))
        self.assertEqual(values["employee_ids"], ["e1", "e2"])
        self.assertEqual(values["project_details"], {"address": "ΒΙΠΕ Σίνδου"})
        self.assertEqual(values["support_roles"], {
            "transfer_driver": "Κώστας", "return_driver": "Νίκο", "supervisor": "Ελένη",
        })

    def test_distinguishes_full_project_name_phone_and_hours(self):
        values, warnings = self.parse(
            "ISOMAT Αποθήκη 7 π.μ. με 3 μ.μ., 20/11. Διεύθυνση Λεωφ. Νίκης 3, Θεσσαλονίκη\n"
            "Τηλ. υπευθύνου: +30 2310 000000"
        )
        self.assertFalse(warnings)
        self.assertEqual(values["project_id"], "p2")
        self.assertEqual(values["first_date"], date(2026, 11, 20))
        self.assertEqual((values["start_time"], values["end_time"]), ("07:00", "15:00"))
        self.assertEqual(values["project_details"], {
            "address": "Λεωφ. Νίκης 3, Θεσσαλονίκη", "contact_phone": "+30 2310 000000",
        })

    def test_ambiguous_names_and_conflicting_dates_require_review(self):
        values, warnings = self.parse("Μαρία στο άγνωστο έργο Πέμπτη 20/11, πρωί")
        self.assertNotIn("project_id", values)
        self.assertFalse(values["employee_ids"])
        self.assertIsNone(values["first_date"])
        self.assertIsNone(values["start_time"])
        self.assertTrue(any("Μαρία" in warning for warning in warnings))
        self.assertTrue(any("διαφέρουν" in warning for warning in warnings))

    def test_multiple_dates_are_not_silently_reduced_to_one(self):
        for dates in ("20/11 και 21/11", "20–21/11", "20 και 21/11"):
            with self.subTest(dates=dates):
                values, warnings = self.parse(f"ISOMAT {dates}, 07:00-11:00")
                self.assertIsNone(values["first_date"])
                self.assertEqual(values["start_time"], "07:00")
                self.assertTrue(any("πολλές ημερομηνίες" in warning for warning in warnings))
