"""Live desktop and mobile Gantt charts and their exports."""

from functools import lru_cache
import hashlib

import streamlit as st
from st_click_detector import click_detector

import database
import gantt_engine
import gantt_excel_export
import gantt_export
import gantt_filters
import gantt_html
import gantt_live_sync
import gantt_search
import utils
from gantt_helpers import get_local_today


def _refresh():
    previous_sync = st.session_state.get("last_sync_time")
    database.sync_data_incremental(silent=True)
    if st.session_state.get("last_sync_time") != previous_sync:
        utils.rebuild_schedule_indexes()


def week_data(start_of_week, zoom_factor, visible_project_ids, search_target, *,
              presentation_mode=False):
    state = st.session_state
    assignments = gantt_filters.apply_recurring_project_visibility_filter(
        state.assignments_by_date, visible_project_ids,
    )
    assignments = gantt_search.reveal_search_project(
        assignments, state.assignments_by_date, search_target,
    )
    _, groups, export_data = gantt_engine.generate_gantt_chart(
        start_of_week, zoom_factor, presentation_mode, state.get("local_gantt_version", 0),
        assignments, state.leaves, state.employees, state.projects,
        state.emp_map, state.proj_map,
    )
    return assignments, groups, export_data


def render(start_of_week, zoom_factor, height, visible_project_ids, *,
           search_prefix, detector_key, desktop=False, presentation_mode=False,
           initial_week=None, opening_search=None, on_click=None, can_refresh=None):
    state = st.session_state
    id_prefix = "bar_" if desktop else "mobile_bar_"
    selected_key = "clicked_key" if desktop else "mobile_clicked_key"
    search_target = state.get(f"{search_prefix}_search_target")
    if opening_search is None:
        opening_search = state.pop(f"{search_prefix}_search_pending", False)

    def build(*, first_render):
        if first_render and initial_week is not None:
            assignments, groups, export_data = initial_week
        else:
            assignments, groups, export_data = week_data(
                start_of_week, zoom_factor, visible_project_ids, search_target,
                presentation_mode=presentation_mode,
            )
        focus = gantt_search.find_search_bar(groups, search_target)
        missing_result = first_render and opening_search and not focus
        if on_click is not None and state.get(selected_key) != focus:
            focus = None
        ids = {key: id_prefix + hashlib.md5(key.encode("utf-8")).hexdigest() for key in groups}
        html = gantt_html.build_html_gantt(
            groups, start_of_week, zoom_factor, ids, height,
            focused_key=focus, scroll_to_focus=first_render and opening_search,
        )
        click_map = {value: key for key, value in ids.items()}

        @lru_cache(maxsize=1)
        def visual_excel():
            return gantt_excel_export.create_visual_gantt_excel(
                groups, start_of_week, assignments_by_date=state.assignments_by_date,
            )

        @lru_cache(maxsize=1)
        def weekly_excel():
            return gantt_export.create_gantt_excel(export_data)

        def draw_snapshot():
            if missing_result:
                st.info("Η τοποθέτηση έχει αλλάξει. Διάλεξε ξανά από τα αποτελέσματα.")
            clicked = click_detector(html, key=detector_key)
            if on_click is not None:
                on_click(clicked, click_map)
            if desktop:
                gantt_export.render_gantt_html_export(html, start_of_week)
                gantt_excel_export.render_employee_day_excel_export(get_local_today())
                gantt_excel_export.render_visual_gantt_month_export(assignments, start_of_week)
                gantt_excel_export.render_visual_gantt_excel_export(
                    groups, start_of_week, get_data=visual_excel,
                )
                gantt_export.render_gantt_export(export_data, start_of_week, get_data=weekly_excel)

        return draw_snapshot

    gantt_live_sync.render_live_view(
        utils.supabase, build=build, refresh=_refresh, can_refresh=can_refresh,
    )
