from datetime import date
import unittest
from unittest.mock import patch

import stadium_fixtures as fixtures


def card(when, venue, home="ΑΡΗΣ", away="Ομάδα δοκιμής", stage="1η Αγωνιστική"):
    return f"""
<div class="game_fixture row" id="fixture">
  <div class="info">
    <div class="game_fixture_org">{stage}</div>
    <div class="game_fixture_date">{when}</div>
    <div class="game_fixture_loc">{venue}</div>
  </div>
  <div><h4 class="teamname">{home}</h4></div>
  <div class="scores"><div>–</div></div>
  <div><h4 class="teamname">{away}</h4></div>
</div>
"""


class StadiumFixturesTests(unittest.TestCase):
    def test_parser_checks_club_stadium_and_publication_date(self):
        html = (
            card("29 Νοεμβρίου 2026 <br>19:00", "Κλεάνθης Βικελίδης")
            + card("5 Δεκεμβρίου 2026 <br>19:00", "Ολυμπιακό Στάδιο", home="Άλλη ομάδα", away="ΑΡΗΣ")
            + card("6 Δεκεμβρίου 2026 <br>19:00", "Κλεάνθης Βικελίδης", home="Άλλη ομάδα")
            + card("<br>", "Γήπεδο ΚΛΕΑΝΘΗΣ ΒΙΚΕΛΙΔΗΣ", stage="18η Αγωνιστική")
        )
        schedule = fixtures.parse_schedule(html)
        self.assertEqual(schedule.season, 2026)
        self.assertEqual(
            [(f.date, f.kickoff) for f in schedule.fixtures],
            [(date(2026, 11, 29), "19:00"), (None, "")],
        )
        with self.assertRaises(ValueError):
            fixtures.parse_schedule("<html><p>Προσωρινά μη διαθέσιμο</p></html>")

    def test_published_rescheduling_replaces_seeded_date_but_keeps_other_seasons(self):
        official = fixtures.parse_schedule(card("30 Νοεμβρίου 2026 <br>19:00", "Κλεάνθης Βικελίδης"))
        saved = [
            {"match_date": "2025-11-29", "competition": "Πρωτάθλημα"},
            {"match_date": "2026-11-29", "competition": "Πρωτάθλημα"},
            {"match_date": "2026-12-02", "competition": "Κύπελλο"},
        ]
        rows = fixtures.match_rows(saved, {"Πρωτάθλημα": official}, date(2025, 11, 1), date(2027, 1, 1))
        self.assertEqual([r["match_date"] for r in rows], ["2025-11-29", "2026-11-30", "2026-12-02"])

    def test_network_failure_keeps_last_successful_schedules(self):
        schedule = fixtures.parse_schedule(card("29 Νοεμβρίου 2026", "Κλεάνθης Βικελίδης"))
        cache = fixtures.ScheduleCache()
        with patch.object(fixtures, "fetch_schedule", return_value=schedule) as fetch:
            self.assertEqual(cache.get(), (dict.fromkeys(fixtures.SOURCES, schedule), ()))
            cache.get()
            self.assertEqual(fetch.call_count, len(fixtures.SOURCES))
            fetch.side_effect = TimeoutError
            previous, failed = cache.get(refresh=True)
        self.assertEqual(previous, dict.fromkeys(fixtures.SOURCES, schedule))
        self.assertEqual(failed, tuple(fixtures.SOURCES))
