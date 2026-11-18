"""Load the periodic-work API after a live update of a Streamlit page."""

from importlib import reload
from threading import Lock


_load_lock = Lock()
_required_functions = ('spacing_review_control', 'confirm_spacing', 'spacing_warnings', 'target_for_period')


def load_periodic_visits():
    with _load_lock:
        import periodic_visits

        # A running process can rerun a new page with the old helper still loaded.
        if not all(callable(getattr(periodic_visits, name, None)) for name in _required_functions):
            periodic_visits = reload(periodic_visits)
        return periodic_visits
