"""Optional placement contacts, compatible with the existing notes/RPC schema.

Human-readable tags use the same notes transport as leave/conflict annotations.
They are edited separately, never as employee assignments. No migration needed.
"""
import hashlib
import json
import re
import unicodedata


LABELS = {
    "transfer_driver": "Οδηγός μεταφοράς",
    "return_driver": "Οδηγός επιστροφής",
    "supervisor": "Επόπτης",
}
_POSITIONS = {
    "transfer_driver": "ΟΔΗΓΟΣ",
    "return_driver": "ΟΔΗΓΟΣ",
    "supervisor": "ΕΠΟΠΤΗΣ",
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


def _position(value):
    text = unicodedata.normalize("NFD", str(value or "").strip().upper())
    return "".join(char for char in text if not unicodedata.combining(char))


def inputs(*, key, defaults=None, stacked=False):
    import streamlit as st

    values = normalize(defaults)
    names_by_position = {position: set() for position in _POSITIONS.values()}
    for employee in st.session_state.get("employees", []):
        if not isinstance(employee, dict) or employee.get("status", "Ενεργός") != "Ενεργός":
            continue
        position = _position(employee.get("position"))
        name = str(employee.get("name") or "").strip()
        if position in names_by_position and name:
            names_by_position[position].add(name)

    st.caption("Μεταφορά και εποπτεία — όλα τα πεδία είναι προαιρετικά.")
    containers = [st] * len(LABELS) if stacked else st.columns(len(LABELS))
    selected = {}
    for container, (field, label) in zip(containers, LABELS.items()):
        names = names_by_position[_POSITIONS[field]]
        current = values[field]
        options = ["", *sorted(names, key=lambda name: (_position(name), name))]
        if current and current not in names:
            # Keep older contact names and values pasted from text or the clipboard.
            options.append(current)
        selected[field] = container.selectbox(
            label, options=options, index=options.index(current),
            format_func=lambda name: name or "— Χωρίς επιλογή —",
            key=f"{key}_{field}",
        )
    return selected
