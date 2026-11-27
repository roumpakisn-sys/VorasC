from datetime import datetime, timedelta
import re


def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()


def normalize_id_list(values):
    """Κρατάει σειρά και αφαιρεί κενά/διπλότυπα ids για ασφαλείς συγκρίσεις."""
    clean = []
    for value in values or []:
        if not value:
            continue
        if value not in clean:
            clean.append(value)
    return clean


def clean_conflict_leave_notes(notes):
    """Αφαιρεί τεχνικές σημειώσεις [Άδεια: ...] / [Εμπλοκή: ...] από το κείμενο."""
    clean = re.sub(r"\[(?:Άδεια|Εμπλοκή):.*?\]", "", notes or "")
    clean = re.sub(r"\s*\|\s*", " ", clean).strip()
    return clean


def assignment_color(assignment, project):
    """Resolve the displayed Gantt color, including legacy rows without an override."""
    return assignment.get("colorHex") or (project or {}).get("color") or "#999999"


def assignment_absence_names(notes):
    text = notes or ""
    named_leaves = re.findall(r"\[Άδεια:\s*([^\]]+)\]", text, flags=re.IGNORECASE)
    recurring_leaves = re.findall(r"\[Μη διαθέσιμος:\s*([^\]]+?)\s*—\s*Άδεια\s*\]", text, flags=re.IGNORECASE)
    return {name.strip() for name in (*named_leaves, *recurring_leaves) if name.strip()}


def record_assignment_absence(notes, employee_name):
    """Attach the existing internal leave annotation before reassigning a shift."""
    text = notes or ""
    name = " ".join(str(employee_name or "").replace("[", " ").replace("]", " ").split())
    if not name or any(name.casefold() == saved.casefold() for saved in assignment_absence_names(text)):
        return text
    return f"{text.rstrip()} [Άδεια: {name}]".strip()
