"""Client email copy templates for a scheduled Gantt bar."""
from html import escape
import re


_WEEKDAYS = ("τη Δευτέρα", "την Τρίτη", "την Τετάρτη", "την Πέμπτη",
             "την Παρασκευή", "το Σάββατο", "την Κυριακή")
_MENU_LABEL = "Αντιγραφή κειμένου email"
_MENU_PATTERN = re.compile(r"<select class='gantt-email-select'[^>]*>.*?</select>", re.DOTALL)


def _person(name, card=""):
    card = str(card or "").strip()
    return f"{name} με ΑΔΤ: {card}" if card else name


def drafts(group, employees_by_id):
    """Return paste-ready text suitable for the actual status of the placement."""
    project = group["Project"]
    day = group["Date"]
    when = f"{_WEEKDAYS[day.weekday()]} {day:%d/%m}"
    start, end = group["StartTime"], group["EndTime"]
    slot = f"{when}, με ώρα έναρξης {start}"
    work = f"οι εργασίες καθαριότητας για το έργο «{project}»"

    def message(*paragraphs):
        return "\n\n".join(part for part in ("Καλησπέρα σας,", *paragraphs, "Με εκτίμηση,") if part)

    if group.get("is_cancelled"):
        return {"Ενημέρωση ακύρωσης": message(
            f"Θα θέλαμε να σας ενημερώσουμε ότι {work}, που είχαν προγραμματιστεί για {slot}, ακυρώθηκαν."
        )}

    crew = []
    for employee_id in dict.fromkeys(group.get("EmployeeIds", ())):
        employee = employees_by_id.get(employee_id, {})
        name = str(employee.get("name") or "").strip()
        if name:
            crew.append(f"- {_person(name, employee.get('id_number'))}")

    supervisor = (group.get("SupportRoles") or {}).get("supervisor", "").strip()
    supervisor_line = ""
    if supervisor:
        normalized = " ".join(supervisor.casefold().split())
        matches = [employee for employee in employees_by_id.values()
                   if " ".join(str(employee.get("name") or "").casefold().split()) == normalized]
        supervisor_card = matches[0].get("id_number") if len(matches) == 1 else None
        supervisor_line = f"Επόπτης εργασιών: {_person(supervisor, supervisor_card)}"

    crew_block = "\n".join(("Ομάδα καθαριότητας:", *crew)) if crew else ""
    replacement_block = "\n".join(("Την αντικατάσταση θα αναλάβουν:", *crew)) if crew else ""
    if len(crew) == 1:
        replacement_block = f"Την αντικατάσταση θα αναλάβει:\n{crew[0]}"

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

    if not replacement_block:
        replacement_block = "Θα σας ενημερώσουμε για το προσωπικό που θα καλύψει την εργασία."

    return {
        "Προγραμματισμός / έναρξη έργου": message(scheduled, crew_block, supervisor_line, closing),
        "Αντικατάσταση προσωπικού": message(replacement, replacement_block, supervisor_line, closing),
        "Ενημέρωση πελάτη": message(update, supervisor_line, closing),
    }


def menu_html(group, employees_by_id, *, compact=False):
    style = " style='top:22px;right:2px;'" if compact else ""
    options = ["<option value=''>▾</option>"]
    for label, body in drafts(group, employees_by_id).items():
        options.append(f"<option data-email-copy='{escape(body, quote=True)}'>{escape(label)}</option>")
    return (
        f"<select class='gantt-email-select' aria-label='{_MENU_LABEL}' title='{_MENU_LABEL}'{style}>"
        + "".join(options) + "</select>"
    )


def without_email_menu(chart_html):
    """Keep the client correspondence menu out of downloaded charts."""
    return _MENU_PATTERN.sub("", chart_html)
