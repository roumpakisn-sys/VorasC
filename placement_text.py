"""Read common Greek scheduling phrases into a local placement draft."""
from collections import defaultdict
from datetime import date, time, timedelta
import re
import unicodedata


_ACCENTS = str.maketrans("άέήίόύώϊΐϋΰς", "αεηιουωιιυυσ")
_WEEKDAYS = "δευτερα τριτη τεταρτη πεμπτη παρασκευη σαββατο κυριακη".split()
_DAY_WORDS = {"σημερα": 0, "αυριο": 1, "μεθαυριο": 2}
_DAY = re.compile(r"\b(?:(επομενη|επομενο)\s+)?(" + "|".join(_WEEKDAYS + list(_DAY_WORDS)) + r")\b")
_DATE = re.compile(
    r"(?<![\w/])(?:\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2}-\d{4}|"
    r"\d{1,2}/\d{1,2}(?:/\d{4}|/\d{2})?)(?![\w/])"
)
_DATE_LIST = re.compile(r"(?<![\d/:])\d{1,2}\s*(?:[,–—-]|και)\s*(?=\d{1,2}/\d)")
_HOUR = r"\d{1,2}(?:[:.]\d{2})?"
_PERIOD = r"(?:π\.?\s*μ\.?|μ\.?\s*μ\.?|(?:το\s+)?(?:πρωι|μεσημερι|απογευμα|βραδυ))(?!\w)"
_RANGE = re.compile(
    rf"(?<![\w/:.])(?P<start>{_HOUR})\s*(?P<start_period>{_PERIOD})?\s*"
    rf"(?:[-–—]|με\b|εωσ\b|ωσ\b|μεχρι\b)\s*"
    rf"(?P<end>{_HOUR})\s*(?P<end_period>{_PERIOD})?(?![\w/:])"
)
_ARRIVAL = re.compile(
    rf"(?:στισ?\s+)?(?P<hour>{_HOUR})(?:\s*(?P<period>{_PERIOD}))?(?![\w:/]|\.\d)"
)
_FIELDS = re.compile(
    r"(?<!\w)(?:"
    r"(?P<address>διευθυνση)\b|"
    r"(?P<contact_phone>τηλεφωνο\b|τηλ\b\.?)\s*(?:υπευθυνου\b)?|"
    r"(?P<transfer_driver>οδηγοσ\s+μεταφορασ\b|μεταφορα\b(?:\s+με\b)?|(?:τουσ\s+)?παει\s+[οη]\b)|"
    r"(?P<return_driver>οδηγοσ\s+επιστροφησ\b|επιστροφη\s+με\b)|"
    r"(?P<supervisor>εποπτησ\b|εποπτρια\b)|"
    r"(?P<arrival_time>(?:ωρα\s+)?προσελευσησ?\b)|"
    r"(?P<custom_project>νεο\s+εργο\s*[:=])|"
    r"(?P<notes>παρατηρησεισ\s*[:=]|σημειωση\s*[:=])"
    r")\s*[:=–—-]?\s*"
)
_FIELD_END = re.compile(r"[;\n]|(?<!\b[^\W\d_])(?<!\bλεωφ)(?<!\bαγ)(?<!\bαρ)\.(?=\s+[^\W\d_])")
_IMPLICIT_ADDRESS = re.compile(r"\b(?:β\.?ι\.?π\.?ε\.?|οδοσ|λεωφοροσ)\s+[^;\n,!]+")
_PHONE = re.compile(r"\+?\d[\d ().-]*")


def _fold(value):
    # Keep offsets so matched addresses, contacts and notes keep their spelling.
    return value.replace("İ", "i").lower().translate(_ACCENTS)


def _mask(text, spans):
    result = list(text)
    for start, end in spans:
        result[start:end] = " " * (end - start)
    return "".join(result)


def _extract_fields(text):
    roles, details, extra = {}, {}, {}
    spans, warnings = [], []
    fields = list(_FIELDS.finditer(_fold(text)))
    for index, marker in enumerate(fields):
        key = marker.lastgroup
        limit = fields[index + 1].start() if index + 1 < len(fields) else len(text)
        value_start = marker.end()
        chunk = text[value_start:limit]
        separator = _FIELD_END.search(_fold(chunk)) if key != "notes" else re.search(r"[;\n]", chunk)
        if separator:
            chunk = chunk[:separator.start()]
        if key in {"transfer_driver", "return_driver", "supervisor", "custom_project"}:
            chunk = chunk.split(",", 1)[0]
        if key == "contact_phone":
            phone = _PHONE.match(chunk)
            chunk = phone[0] if phone else ""
        if key == "arrival_time":
            arrival = _ARRIVAL.match(_fold(chunk))
            spans.append((marker.start(), value_start + (arrival.end() if arrival else 0)))
            if arrival:
                try:
                    clock = _clock(arrival["hour"], arrival["period"])
                    extra.update(arrival_time=clock.isoformat(timespec="minutes"), use_arrival=True)
                    continue
                except ValueError:
                    pass
            warnings.append("Έλεγξε την ώρα προσέλευσης στη φόρμα.")
            continue
        value = chunk.strip(" \t,.:;*")
        spans.append((marker.start(), value_start + len(chunk)))
        if not value:
            continue
        if key in {"address", "contact_phone"}:
            details[key] = value
        elif key in {"transfer_driver", "return_driver", "supervisor"}:
            roles[key] = re.sub(r"^(?:ο|η|τον|την)\s+", "", value, flags=re.IGNORECASE)
        else:
            extra[key] = value
    return extra, roles, details, _mask(text, spans), warnings


def _date_value(text, today):
    folded = _fold(text)
    dates, words = list(_DATE.finditer(folded)), list(_DAY.finditer(folded))
    spans = [m.span() for m in dates + words]
    short_dates = list(_DATE_LIST.finditer(folded))
    time_spans = [m.span() for m in _RANGE.finditer(_mask(folded, spans))] if short_dates else []
    if len(dates) > 1 or any(
        not any(start <= m.start() < end for start, end in time_spans) for m in short_dates
    ):
        return None, spans, "Βρέθηκαν πολλές ημερομηνίες. Επίλεξε τις ημέρες στη φόρμα."
    if dates:
        raw = dates[0][0]
        try:
            if re.match(r"^\d{4}-", raw):
                result = date.fromisoformat(raw)
            else:
                day, month, *years = re.split(r"[/\-]", raw)
                year = years[0] if years else str(today.year)
                result = date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
        except ValueError:
            return None, spans, "Η ημερομηνία του κειμένου δεν είναι έγκυρη."
        for word in words:
            day_word = word[2]
            agrees = (result == today + timedelta(days=_DAY_WORDS[day_word])
                      if day_word in _DAY_WORDS else result.weekday() == _WEEKDAYS.index(day_word))
            if not agrees:
                return None, spans, "Η ημερομηνία και η ημέρα στο κείμενο διαφέρουν."
        return result, spans, ""
    if len(words) == 1:
        word = words[0][2]
        if word in _DAY_WORDS:
            return today + timedelta(days=_DAY_WORDS[word]), spans, ""
        weekday = _WEEKDAYS.index(word)
        offset = ((weekday - today.weekday()) % 7 if not words[0][1]
                  else 7 + weekday - today.weekday())
        return today + timedelta(days=offset), spans, ""
    return None, spans, "Επίλεξε ημερομηνία στη φόρμα."


def _clock(value, period):
    hour, _, minutes = value.replace(".", ":").partition(":")
    hour = int(hour)
    if period and 1 <= hour <= 12:
        afternoon = _fold(period).removeprefix("το ").startswith(("μ", "α", "β"))
        hour = hour % 12 + (12 if afternoon else 0)
    return time(hour, int(minutes or 0))


def _hours_value(text):
    matches = list(_RANGE.finditer(_fold(text)))
    spans = [m.span() for m in matches]
    if len(matches) == 1:
        match = matches[0]
        try:
            start = _clock(match["start"], match["start_period"] or match["end_period"])
            end = _clock(match["end"], match["end_period"])
            if start < end:
                return start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), spans, ""
        except ValueError:
            pass
    return None, None, spans, "Συμπλήρωσε ένα έγκυρο ωράριο Έναρξης–Λήξης στη φόρμα."


def _names(records, *, people=False, short=False):
    names = defaultdict(set)
    for record in records:
        label = str(record.get("name") or "").strip()
        words = _fold(unicodedata.normalize("NFC", label)).split()
        if short:
            aliases = [word.strip(".") for word in words if word.strip(".").isalpha() and len(word.strip(".")) >= 3]
        elif not people or len(words) > 1:
            aliases = [" ".join(words)]
            if people and len(words) == 2:
                aliases.append(" ".join(reversed(words)))
        else:
            aliases = []
        for alias in filter(None, aliases):
            names[alias].add(record["id"])
    return names


def _name_matches(text, names):
    if not names:
        return set(), [], []
    ordered = sorted(names, key=lambda name: (-len(name), name))
    alternatives = [r"\s+".join(map(re.escape, name.split())) for name in ordered]
    matcher = re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)")
    found, ambiguous, spans = set(), [], []
    for match in matcher.finditer(_fold(text)):
        ids = names[" ".join(match[0].split())]
        if len(ids) == 1:
            found.update(ids)
        else:
            ambiguous.append(text[match.start():match.end()])
        spans.append(match.span())
    return found, ambiguous, spans


def parse(text, projects, employees, today):
    """Return prefill values and any ambiguities for the user to review."""
    text = unicodedata.normalize("NFC", text.strip())
    draft, roles, details, main, warnings = _extract_fields(text)
    if not draft.get("custom_project"):
        project_ids, ambiguous, spans = _name_matches(main, _names(projects))
        main = _mask(main, spans)
        if len(project_ids) == 1 and not ambiguous:
            draft["project_id"] = next(iter(project_ids))
        else:
            warnings.append("Επίλεξε το έργο στη φόρμα.")

    first_date, spans, date_warning = _date_value(main, today)
    main = _mask(main, spans)
    start, end, spans, time_warning = _hours_value(main)
    main = _mask(main, spans)
    warnings.extend(warning for warning in (date_warning, time_warning) if warning)
    if not details.get("address"):
        address = _IMPLICIT_ADDRESS.search(_fold(main))
        if address:
            address_end = address.start() + len(address[0].rstrip())
            details["address"] = text[address.start():address_end].strip(" ,.;*\t")
            main = _mask(main, [address.span()])

    people = [record for record in employees if record.get("status", "Ενεργός") == "Ενεργός"]
    ids, ambiguous, spans = _name_matches(main, _names(people, people=True))
    more_ids, short_ambiguities, _ = _name_matches(_mask(main, spans), _names(people, short=True))
    ids.update(more_ids)
    uncertain = list(dict.fromkeys(ambiguous + short_ambiguities))
    if uncertain:
        warnings.append("Επίλεξε το σωστό άτομο για " + ", ".join(uncertain) + ".")

    draft.update(
        first_date=first_date,
        start_time=start,
        end_time=end,
        employee_ids=[record["id"] for record in people if record["id"] in ids],
        project_details=details,
        support_roles=roles,
    )
    return draft, warnings
