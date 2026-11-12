"""Atomic multi-worker Gantt replacement through one PostgreSQL RPC.

There is intentionally NO non-transactional fallback. On a lost HTTP response,
read back the database before claiming the change failed or succeeded.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

RPC_NAME = "staffpro_replace_bar_atomic"


def _json_value(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _json_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_value(x) for x in v]
    return v


def _same_row(saved: dict, expected: dict) -> bool:
    for key, value in expected.items():
        if key == "updated_at":
            continue  # DB triggers can normalize this field.
        actual = saved.get(key)
        if isinstance(value, (date, datetime)):
            if str(actual or "")[:10] != value.isoformat()[:10]:
                return False
        elif str(actual or "") != str(value or ""):
            return False
    return True


def _read_back(supabase, originals: list[dict], replacements: list[dict], project: dict | None):
    """Return True iff every old row is gone and every expected new row exists."""
    ids_old = [str(row["id"]) for row in originals]
    ids_new = [str(row["id"]) for row in replacements]
    checked_old = supabase.table("assignments").select("id").in_("id", ids_old).execute()
    checked_new = supabase.table("assignments").select("*").in_("id", ids_new).execute()
    by_new = {str(row.get("id")): row for row in (checked_new.data or [])}
    if checked_old.data or len(by_new) != len(ids_new):
        return False
    if any(not _same_row(by_new[str(x["id"])], x) for x in replacements):
        return False
    if project:
        checked_project = supabase.table("projects").select("id").eq("id", project["id"]).execute()
        if len(checked_project.data or []) != 1:
            return False
    return True


def replace_bar(supabase, originals: list[dict], replacements: list[dict], project: dict | None = None):
    """Returns (status, message), status in {'saved', 'rejected', 'unknown'}.

    'unknown' is never safe to retry blindly: a connection error can happen
    AFTER PostgreSQL committed the transaction.
    """
    if supabase is None:
        return "rejected", "Απαιτείται σύνδεση Supabase."
    if not originals or not replacements:
        return "rejected", "Δεν υπάρχουν εγγραφές προς αντικατάσταση."
    expected = {_json_value(row)["id"]: _json_value(row) for row in replacements}
    if len(expected) != len(replacements):
        return "rejected", "Οι νέες βάρδιες πρέπει να έχουν μοναδικά IDs."
    payload = {
        "p_originals": _json_value(originals),
        "p_replacements": list(expected.values()),
        "p_new_project": _json_value(project) if project else None,
    }
    try:
        response = supabase.rpc(RPC_NAME, payload).execute()
        result = response.data or {}
        if (isinstance(result, dict) and result.get("ok") is True
                and int(result.get("removed", -1)) == len(originals)
                and int(result.get("inserted", -1)) == len(replacements)):
            return "saved", "Η αλλαγή αποθηκεύτηκε με μία συναλλαγή."
        # A request could commit but response parsing fail; do a read-back.
        try:
            if _read_back(supabase, originals, replacements, project):
                return "saved", "Η αλλαγή επιβεβαιώθηκε με επαλήθευση στη βάση."
        except Exception:
            pass
        return "unknown", "Δεν επιβεβαιώθηκε η αποθήκευση. Ανανέωσε τα δεδομένα πριν επιχειρήσεις ξανά."
    except Exception as exc:
        try:
            if _read_back(supabase, originals, replacements, project):
                return "saved", "Η σύνδεση διακόπηκε, αλλά η αποθήκευση επιβεβαιώθηκε στη βάση."
        except Exception:
            pass
        # Even missing RPC functions cause a rejected request; no changes applied.
        if "PGRST202" in str(exc) or ("staffpro_replace_bar_atomic" in str(exc) and "not found" in str(exc).lower()):
            return "rejected", (
                "Η ασφαλής λειτουργία αποθήκευσης δεν έχει εγκατασταθεί. "
                "Εκτέλεσε το sql/atomic_gantt_bar_replacement.sql στο Supabase SQL Editor."
            )
        return "unknown", (
            "Αβέβαιο αποτέλεσμα αποθήκευσης (πιθανή διακοπή σύνδεσης). "
            "Ανανέωσε και έλεγξε τις παλιές/νέες βάρδιες πριν από νέα προσπάθεια. "
            f"Τεχνικό σφάλμα: {exc}"
        )
