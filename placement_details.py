"""Optional address/phone for a placement, carried by the existing notes schema."""
import hashlib
import json
import re


LABELS = {"address": "Διεύθυνση", "contact_phone": "Τηλ. υπευθύνου"}
_KEYS = {label: key for key, label in LABELS.items()}
_TAG = re.compile(r"\[(" + "|".join(re.escape(label) for label in LABELS.values())
                  + r"): ((?:\\.|[^\[\]\\])*)\]")


def normalize(details=None):
    return {key: str((details or {}).get(key) or "").strip() for key in LABELS}


def split_notes(notes):
    values = normalize()
    text = notes or ""

    def extract(match):
        values[_KEYS[match[1]]] = re.sub(r"\\([\\\[\]])", r"\1", match[2]).strip()
        return ""

    clean = _TAG.sub(extract, text)
    return (clean.strip() if clean != text else text), values


def combine_notes(notes, details):
    """Replace/clear just these fields, preserving role and leave annotations."""
    clean, _ = split_notes(notes)
    tags = []
    for key, value in normalize(details).items():
        if value:
            escaped = re.sub(r"([\\\[\]])", r"\\\1", value)
            tags.append(f"[{LABELS[key]}: {escaped}]")
    return " ".join([clean.rstrip(), *tags]).strip() if tags else clean


def group_suffix(details):
    values = normalize(details)
    if not any(values.values()):
        return ""
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "_details_" + hashlib.sha256(payload).hexdigest()[:20]


def project_label(project, details):
    """Display text only: never modify the project's actual name or identity."""
    values = normalize(details)
    parts = [str(project)]
    if values["address"]:
        parts.append("📍 " + values["address"])
    if values["contact_phone"]:
        parts.append("☎️ Τηλ. υπευθύνου: " + values["contact_phone"])
    return " | ".join(parts)


def inputs(*, key, defaults=None, stacked=False):
    import streamlit as st

    values = normalize(defaults)
    st.caption("Στοιχεία έργου — προαιρετικά.")
    containers = [st] * len(LABELS) if stacked else st.columns(len(LABELS))
    return {field: container.text_input(label, value=values[field], key=f"{key}_{field}")
            for container, (field, label) in zip(containers, LABELS.items())}
