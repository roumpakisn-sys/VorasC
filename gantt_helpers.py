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
