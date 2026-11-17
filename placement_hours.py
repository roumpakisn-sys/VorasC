"""Optional worked duration, stored with existing placement metadata in notes."""
import math
import re


LABEL = 'Πραγματικές ώρες'
_TAG = re.compile(r'\[Πραγματικές ώρες:\s*([^\]]+)\]')


def normalize(value):
    if value is None or value == '':
        return None
    hours = float(str(value).replace(',', '.'))
    if not math.isfinite(hours) or not 0 <= hours <= 24:
        raise ValueError('Οι πραγματικές ώρες πρέπει να είναι από 0 έως 24.')
    return round(hours, 2)


def split_notes(notes):
    value = None
    text = notes or ''

    def extract(match):
        nonlocal value
        try:
            value = normalize(match[1])
        except ValueError:
            return match[0]
        return ''

    clean = _TAG.sub(extract, text)
    return (clean.strip() if clean != text else text), value


def combine_notes(notes, hours):
    clean, _ = split_notes(notes)
    value = normalize(hours)
    return f'{clean.rstrip()} [{LABEL}: {value:g}]'.strip() if value is not None else clean


def group_suffix(hours):
    value = normalize(hours)
    return f'_hours_{value:g}' if value is not None else ''


def counted_minutes(assignment):
    """Worked duration overrides scheduled duration, including an explicit zero."""
    if assignment.get('is_cancelled'):
        return 0.0
    actual = split_notes(assignment.get('notes'))[1]
    if actual is not None:
        return actual * 60
    try:
        start_h, start_m = map(int, str(assignment.get('startTime') or '')[:5].split(':'))
        end_h, end_m = map(int, str(assignment.get('endTime') or '')[:5].split(':'))
        if not (0 <= start_h < 24 and 0 <= end_h < 24 and 0 <= start_m < 60 and 0 <= end_m < 60):
            return 0.0
        return float(((end_h * 60 + end_m) - (start_h * 60 + start_m)) % 1440)
    except (TypeError, ValueError):
        return 0.0


def counted_hours(assignment):
    return round(counted_minutes(assignment) / 60, 2)


def inputs(*, key, default=None):
    import streamlit as st

    return st.number_input(
        'Πραγματικές ώρες εργασίας (προαιρετικό)', min_value=0.0, max_value=24.0,
        value=normalize(default), step=0.25, format='%.2f', key=key,
        placeholder='Κενό = διάρκεια μπάρας',
        help='Σύνολο ωρών ανά εργαζόμενο και ανά ημέρα αυτής της μπάρας. '
             'Π.χ. 6,5 = 6 ώρες και 30 λεπτά. Κενό: μετρά το ωράριο της μπάρας. '
             'Το 0 μετρά ως μηδέν ώρες.',
    )
