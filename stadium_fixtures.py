"""Published Aris football fixtures from the club's official competition pages."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from http.client import HTTPException
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen
import re

from stadium_tracking import _normalized_label


SOURCES = {
    "Πρωτάθλημα": "https://arisfc.com.gr/el/season/stoiximan-super-league.html",
    "Κύπελλο": "https://arisfc.com.gr/el/season/kypello-ellados.html",
}
MONTHS = (
    "ΙΑΝΟΥΑΡΙΟΥ", "ΦΕΒΡΟΥΑΡΙΟΥ", "ΜΑΡΤΙΟΥ", "ΑΠΡΙΛΙΟΥ", "ΜΑΙΟΥ", "ΙΟΥΝΙΟΥ",
    "ΙΟΥΛΙΟΥ", "ΑΥΓΟΥΣΤΟΥ", "ΣΕΠΤΕΜΒΡΙΟΥ", "ΟΚΤΩΒΡΙΟΥ", "ΝΟΕΜΒΡΙΟΥ", "ΔΕΚΕΜΒΡΙΟΥ",
)
TEAM_NAMES = {"ΑΡΗΣ", "ΠΑΕ ΑΡΗΣ", "ARIS", "ARIS FC"}


@dataclass(frozen=True)
class Fixture:
    date: date | None
    kickoff: str
    opponent: str
    round: str


@dataclass(frozen=True)
class Schedule:
    season: int
    fixtures: tuple[Fixture, ...]


class FixtureParser(HTMLParser):
    """Read the fixture card fields without relying on translated page headings."""
    fields = {
        "game_fixture_date": "date",
        "game_fixture_loc": "venue",
        "game_fixture_org": "round",
        "teamname": "team",
    }

    def __init__(self):
        super().__init__()
        self.cards = []
        self.card = None
        self.depth = 0
        self.capture = None
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if self.card is None:
            if tag == "div" and "game_fixture" in classes:
                self.card = {"team": []}
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        if self.capture:
            if tag == "br":
                self.chunks.append(" ")
            return
        field = next((self.fields[name] for name in classes if name in self.fields), None)
        if field:
            self.capture = (tag, self.depth, field)
            self.chunks = []

    def handle_data(self, data):
        if self.capture:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if self.capture and self.capture[:2] == (tag, self.depth):
            field = self.capture[2]
            value = " ".join("".join(self.chunks).split())
            if field == "team":
                self.card["team"].append(value)
            else:
                self.card[field] = value
            self.capture = None
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.cards.append(self.card)
                self.card = None


def season_for(day):
    return day.year - (day.month < 7)


def _fixture_date(value):
    match = re.search(r"\b(\d{1,2}) ([Α-Ω]+) (\d{4})\b", _normalized_label(value))
    if not match or match[2] not in MONTHS:
        return None
    try:
        return date(int(match[3]), MONTHS.index(match[2]) + 1, int(match[1]))
    except ValueError:
        return None


def parse_schedule(html):
    parser = FixtureParser()
    parser.feed(html)
    parser.close()
    seasons = Counter()
    fixtures = []
    for card in parser.cards:
        teams = card["team"]
        if len(teams) != 2:
            continue
        our_team = next((index for index, name in enumerate(teams) if _normalized_label(name) in TEAM_NAMES), None)
        if our_team is None:
            continue
        published = card.get("date", "")
        day = _fixture_date(published)
        if day:
            seasons[season_for(day)] += 1
        if "ΚΛΕΑΝΘΗΣ ΒΙΚΕΛΙΔΗΣ" not in _normalized_label(card.get("venue")):
            continue
        kickoff = re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", published)
        fixtures.append(Fixture(day, kickoff[0].zfill(5) if day and kickoff else "",
                                teams[1 - our_team], card.get("round", "")))
    if not seasons:
        raise ValueError("Το πρόγραμμα της ΠΑΕ ΑΡΗΣ δεν αναγνωρίστηκε.")
    season = seasons.most_common(1)[0][0]
    current = {fixture for fixture in fixtures if fixture.date is None or season_for(fixture.date) == season}
    return Schedule(season, tuple(sorted(
        current, key=lambda f: (f.date or date.max, f.kickoff, f.round, f.opponent),
    )))


def fetch_schedule(url):
    request = Request(url, headers={"User-Agent": "VorasC Stadium Calendar/1.0"})
    with urlopen(request, timeout=8) as response:
        html = response.read(2_000_001)
        if len(html) > 2_000_000:
            raise ValueError("Το πρόγραμμα ξεπέρασε το μέγεθος ανάγνωσης.")
        return parse_schedule(html.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))


class ScheduleCache:
    """Retain each successful source independently across Streamlit reruns."""
    def __init__(self):
        self._lock = Lock()
        self._schedules = {}
        self._failed = ()
        self._valid_until = 0

    def get(self, *, refresh=False):
        with self._lock:
            if refresh or monotonic() >= self._valid_until:
                failures = []
                with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
                    requests = {kind: pool.submit(fetch_schedule, url) for kind, url in SOURCES.items()}
                    for kind, request in requests.items():
                        try:
                            self._schedules[kind] = request.result()
                        except (OSError, HTTPException, ValueError, LookupError):
                            failures.append(kind)
                self._failed = tuple(failures)
                self._valid_until = monotonic() + (300 if failures else 3 * 60 * 60)
            return dict(self._schedules), self._failed


def match_rows(saved, schedules, start, end):
    """Use published dates for each covered season, with saved dates outside that coverage."""
    rows = []
    for row in saved:
        day = date.fromisoformat(str(row["match_date"]))
        schedule = schedules.get(row["competition"])
        if start <= day < end and (not schedule or schedule.season != season_for(day)):
            rows.append(row)
    for kind, schedule in schedules.items():
        rows.extend(
            {"match_date": fixture.date.isoformat(), "competition": kind,
             "kickoff": fixture.kickoff, "opponent": fixture.opponent}
            for fixture in schedule.fixtures if fixture.date and start <= fixture.date < end
        )
    return sorted(rows, key=lambda row: (row["match_date"], row["competition"], row.get("kickoff", "")))
