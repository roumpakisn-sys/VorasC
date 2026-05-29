import streamlit as st
from datetime import timedelta

from gantt_helpers import get_local_today


def render_gantt_controls(clear_bar_selection):
    """
    Render του πάνω control panel του Gantt.

    Επιστρέφει:
    start_of_week, zoom_level, zoom_factor, presentation_mode, gantt_height_px
    """

    def sync_from_widget():
        st.session_state.view_week_date = st.session_state.date_picker
        clear_bar_selection()

    def go_prev_week():
        new_date = st.session_state.view_week_date - timedelta(days=7)
        st.session_state.view_week_date = new_date
        st.session_state.date_picker = new_date
        clear_bar_selection()

    def go_next_week():
        new_date = st.session_state.view_week_date + timedelta(days=7)
        st.session_state.view_week_date = new_date
        st.session_state.date_picker = new_date
        clear_bar_selection()

    def go_to_today():
        new_date = get_local_today()
        st.session_state.view_week_date = new_date
        st.session_state.date_picker = new_date
        clear_bar_selection()

    # --- ΣΥΜΠΙΕΣΗ ΤΟΥ ΠΑΝΩ ΜΕΡΟΥΣ ΣΕ ΜΙΑ ΣΥΜΠΑΓΗ ΓΡΑΜΜΗ (Compact UI) ---
    st.markdown(
        """
    <style>
    .block-container, [data-testid="block-container"] {
        max-width: 98% !important;
        padding-top: 0.5rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    div[data-testid="stNotification"], .stAlert {
        padding: 2px 10px !important;
        margin-top: 0px !important;
        margin-bottom: 2px !important;
    }
    div[data-testid="stNotification"] p, .stAlert p {
        margin: 0 !important;
        font-size: 13px !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "<h3 style='margin-top: -30px; margin-bottom: 5px;'>📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων</h3>",
        unsafe_allow_html=True,
    )

    col_date, col_nav1, col_nav2, col_today, col_zoom, col_pres = st.columns([1.5, 0.8, 0.8, 0.8, 1.5, 1.5])
    with col_date:
        st.date_input(
            "Εβδομάδα",
            value=st.session_state.view_week_date,
            key="date_picker",
            on_change=sync_from_widget,
            label_visibility="collapsed",
        )
        start_of_week = st.session_state.view_week_date - timedelta(days=st.session_state.view_week_date.weekday())
    with col_nav1:
        st.button("⬅️ Πριν", on_click=go_prev_week, use_container_width=True)
    with col_nav2:
        st.button("Μετά ➡️", on_click=go_next_week, use_container_width=True)
    with col_today:
        st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)
    with col_zoom:
        if "gantt_zoom_level" not in st.session_state:
            st.session_state.gantt_zoom_level = 100
        zoom_level = st.slider(
            "Ζουμ",
            min_value=50,
            max_value=200,
            value=st.session_state.gantt_zoom_level,
            step=5,
            label_visibility="collapsed",
            key="gantt_zoom_slider",
        )
        st.session_state.gantt_zoom_level = zoom_level
    with col_pres:
        presentation_mode = st.checkbox("📺 Πλήρης Προβολή")

    if "gantt_height_px" not in st.session_state:
        st.session_state.gantt_height_px = 650

    gantt_height_px = st.slider(
        "Ύψος Gantt",
        min_value=400,
        max_value=1200,
        value=st.session_state.gantt_height_px,
        step=25,
        help="Αυξομείωση του κάθετου μεγέθους του παραθύρου Gantt.",
        key="gantt_height_slider",
    )

    # Όταν αλλάζει το ύψος, ανανεώνουμε το component key του Gantt.
    # Το st_click_detector μερικές φορές κρατάει παλιό iframe αν το key μείνει ίδιο.
    if st.session_state.get("last_gantt_height_px") != gantt_height_px:
        st.session_state.gantt_height_px = gantt_height_px
        st.session_state.last_gantt_height_px = gantt_height_px
        st.session_state.suppress_next_detector_click = True
        st.session_state.detector_version = st.session_state.get("detector_version", 0) + 1
    else:
        st.session_state.gantt_height_px = gantt_height_px

    zoom_factor = zoom_level / 100.0

    return start_of_week, zoom_level, zoom_factor, presentation_mode, gantt_height_px
