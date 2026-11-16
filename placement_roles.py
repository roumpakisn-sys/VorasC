"""Optional placement contacts, compatible with the existing notes/RPC schema.

Human-readable tags use the same notes transport as leave/conflict annotations.
They are edited separately, never as employee assignments. No migration needed.
"""
import hashlib
import json
import re


LABELS = {
    "transfer_driver": "Οδηγός μεταφοράς",
    "return_driver": "Οδηγός επιστροφής",
    "supervisor": "Επόπτης",
}
_KEYS = {label: key for key, label in LABELS.items()}
_TAG = re.compile(
    r"\[(" + "|".join(re.escape(label) for label in LABELS.values())
    + r"): ((?:\\.|[^\[\]\\])*)\]"
)


def normalize(roles=None):
    return {key: str((roles or {}).get(key) or "").strip() for key in LABELS}


def split_notes(notes):
    """Return free notes and contacts; unrelated/malformed annotations survive."""
    roles = normalize()
    text = notes or ""

    def extract(match):
        roles[_KEYS[match[1]]] = re.sub(r"\\([\\\[\]])", r"\1", match[2]).strip()
        return ""

    clean = _TAG.sub(extract, text)
    # Do not alter legacy free notes when no role tags exist.
    return (clean.strip() if clean != text else text), roles


def combine_notes(notes, roles):
    """Replace all managed tags, allowing individual/all fields to be cleared."""
    clean, _ = split_notes(notes)
    tags = []
    for key, value in normalize(roles).items():
        if value:
            escaped = re.sub(r"([\\\[\]])", r"\\\1", value)
            tags.append(f"[{LABELS[key]}: {escaped}]")
    return " ".join([clean.rstrip(), *tags]).strip() if tags else clean


def group_suffix(roles):
    """Keep old bar identities; different contacts must not merge into one bar."""
    values = normalize(roles)
    if not any(values.values()):
        return ""
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "_roles_" + hashlib.sha256(payload).hexdigest()[:20]


def inputs(*, key, defaults=None, stacked=False):
    import streamlit as st

    values = normalize(defaults)
    st.caption("Μεταφορά και εποπτεία — όλα τα πεδία είναι προαιρετικά.")
    containers = [st] * len(LABELS) if stacked else st.columns(len(LABELS))
    return {
        field: container.text_input(label, value=values[field], key=f"{key}_{field}")
        for container, (field, label) in zip(containers, LABELS.items())
    }
