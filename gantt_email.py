"""Client email copy templates for a scheduled Gantt bar."""
from html import escape
import re
from typing import NamedTuple


_WEEKDAYS = ("τη Δευτέρα", "την Τρίτη", "την Τετάρτη", "την Πέμπτη",
             "την Παρασκευή", "το Σάββατο", "την Κυριακή")
_MENU_PATTERN = re.compile(
    r"<div class='gantt-email-options'>.*?</div>"
    r"|<button type='button' class='gantt-popup-toggle gantt-email-toggle'[^>]*>.*?</button>",
    re.DOTALL,
)


class EmailBody(NamedTuple):
    text: str
    html: str


def _paragraph(text):
    return EmailBody(text, f"<p>{escape(text)}</p>" if text else "")


def _person(name, card="", *, prefix=""):
    card = str(card or "").strip()
    identity = f" με ΑΔΤ: {card}" if card else ""
    return EmailBody(f"{prefix}{name}{identity}", f"{escape(prefix)}<strong>{escape(name)}</strong>{escape(identity)}")


def _people_list(people, heading=""):
    if not people:
        return EmailBody("", "")
    text = "\n".join(line for line in (heading, *(f"- {person.text}" for person in people)) if line)
    items = "".join(f"<li>{person.html}</li>" for person in people)
    return EmailBody(text, f"{_paragraph(heading).html}<ul>{items}</ul>")


def drafts(group, employees_by_id):
    """Return plain and formatted email bodies for the status of the placement."""
    project = group["Project"]
    day = group["Date"]
    when = f"{_WEEKDAYS[day.weekday()]} {day:%d/%m}"
    start, end = group["StartTime"], group["EndTime"]
    slot = f"{when}, με ώρα έναρξης {start}"
    work = f"οι εργασίες καθαριότητας για το έργο «{project}»"

    def message(intro, *sections, closing=""):
        parts = (_paragraph("Καλησπέρα σας,"), _paragraph(intro), *sections,
                 _paragraph(closing), _paragraph("Με εκτίμηση,"))
        return EmailBody(
            "\n\n".join(part.text for part in parts if part.text),
            "".join(part.html for part in parts),
        )

    if group.get("is_cancelled"):
        return {"Ενημέρωση ακύρωσης": message(
            f"Θα θέλαμε να σας ενημερώσουμε ότι {work}, που είχαν προγραμματιστεί για {slot}, ακυρώθηκαν."
        )}

    crew = []
    for employee_id in dict.fromkeys(group.get("EmployeeIds", ())):
        employee = employees_by_id.get(employee_id, {})
        name = str(employee.get("name") or "").strip()
        if name:
            crew.append(_person(name, employee.get("id_number")))

    supervisor = (group.get("SupportRoles") or {}).get("supervisor", "").strip()
    supervision = []
    if supervisor:
        normalized = " ".join(supervisor.casefold().split())
        matches = [employee for employee in employees_by_id.values()
                   if " ".join(str(employee.get("name") or "").casefold().split()) == normalized]
        supervisor_card = matches[0].get("id_number") if len(matches) == 1 else None
        supervision.append(_person(supervisor, supervisor_card, prefix="Επόπτης εργασιών: "))

    supervisor_block = _people_list(supervision)
    crew_block = _people_list(crew, "Ομάδα καθαριότητας:")
    replacement_heading = ("Την αντικατάσταση θα αναλάβει:" if len(crew) == 1
                           else "Την αντικατάσταση θα αναλάβουν:")
    replacement_block = (_people_list(crew, replacement_heading) if crew else
                         _paragraph("Θα σας ενημερώσουμε για το προσωπικό που θα καλύψει την εργασία."))

    if group.get("CustomerConfirmation") is not None:
        scheduled = f"Προτείνουμε να πραγματοποιηθούν {work} {slot}."
        replacement = (
            f"Για τις εργασίες καθαριότητας του έργου «{project}» {when} "
            f"({start}–{end}), προτείνουμε την αντικατάσταση του τακτικού προσωπικού."
        )
        update = f"Για το έργο «{project}» προτείνεται καθαρισμός {when}, {start}–{end}."
        closing = "Παρακαλούμε για την επιβεβαίωσή σας."
    else:
        scheduled = f"Θα θέλαμε να σας ενημερώσουμε ότι {work} έχουν προγραμματιστεί για {slot}."
        replacement = (
            f"Θα θέλαμε να σας ενημερώσουμε ότι {when} το τακτικό προσωπικό του έργου «{project}» "
            f"θα απουσιάζει. Το ωράριο των εργασιών έχει οριστεί για {start}–{end}."
        )
        update = f"Σας ενημερώνουμε ότι {work} έχουν προγραμματιστεί για {when}, {start}–{end}."
        closing = ""

    return {
        "Προγραμματισμός / έναρξη έργου": message(scheduled, crew_block, supervisor_block, closing=closing),
        "Αντικατάσταση προσωπικού": message(replacement, replacement_block, supervisor_block, closing=closing),
        "Ενημέρωση πελάτη": message(update, supervisor_block, closing=closing),
    }


def menu_html(group, employees_by_id):
    buttons = []
    for label, body in drafts(group, employees_by_id).items():
        buttons.append(
            f"<button type='button' data-email-copy='{escape(body.text, quote=True)}' "
            f"data-email-html='{escape(body.html, quote=True)}'>{escape(label)}</button>"
        )
    return "<div class='gantt-email-options'>" + "".join(buttons) + "</div>"


def without_email_menu(chart_html):
    """Keep the client correspondence menu out of downloaded charts."""
    return _MENU_PATTERN.sub("", chart_html)
