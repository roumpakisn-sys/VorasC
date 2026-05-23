import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import io
import textwrap
import time
import re
import hashlib
import base64
from st_click_detector import click_detector

# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "employees" not in st.session_state:
    st.session_state.employees = []
if "projects" not in st.session_state:
    st.session_state.projects = []
if "assignments" not in st.session_state:
    st.session_state.assignments = []
if "leaves" not in st.session_state:
    st.session_state.leaves = []
if "recurring_patterns" not in st.session_state:
    st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state:
    st.session_state.evaluations = []

if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

import config
import utils
import scheduling
import gantt_engine
import ui_dashboard

def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()

utils.init_data_and_sync()

total_indexed = sum(len(v) for v in st.session_state.get("assignments_by_date", {}).values())
if total_indexed != len(st.session_state.get("assignments", [])):
    utils.mark_data_changed()
    utils.init_data_and_sync()

utils.setup_shared_ui()

is_full_admin = st.session_state.get("current_user") != "TAN"
active_employee_ids = [e["id"] for e in st.session_state.employees if e.get("status", "Ενεργός") == "Ενεργός"]

if "clicked_key" not in st.session_state:
    st.session_state.clicked_key = None
if "trigger_scroll" not in st.session_state:
    st.session_state.trigger_scroll = False
if "last_clicked_safe_id" not in st.session_state:
    st.session_state.last_clicked_safe_id = ""
if "detector_version" not in st.session_state:
    st.session_state.detector_version = 0

# --- ΜΗΧΑΝΙΣΜΟΣ ΗΜΕΡΟΜΗΝΙΑΣ ΚΑΙ ΕΚΚΑΘΑΡΙΣΗ ΚΛΙΚ ---
if "view_week_date" not in st.session_state:
    st.session_state.view_week_date = get_local_today()

def clear_bar_selection():
    st.session_state.clicked_key = None
    st.session_state.trigger_scroll = False
    st.session_state.last_clicked_safe_id = ""
    st.session_state.detector_version = st.session_state.get("detector_version", 0) + 1

def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)
    clear_bar_selection()

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)
    clear_bar_selection()

def go_to_today():
    st.session_state.view_week_date = get_local_today()
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

# Κλήση του UI module για το Top Nav
selected_date, start_of_week, zoom_level, presentation_mode = ui_dashboard.render_top_nav(go_prev_week, go_next_week, go_to_today)

st.session_state.gantt_zoom_level = zoom_level
zoom_factor = zoom_level / 100.0

# --- ΕΞΑΓΩΓΗ ΔΕΔΟΜΕΝΩΝ ΑΠΟ ΤΟ ENGINE ---
@st.cache_data(show_spinner=False, max_entries=5)
def get_cached_data(
    start_of_week,
    zoom_factor,
    presentation_mode,
    data_version,
    _assignments_by_date,
    _leaves,
    _employees,
    _projects,
    _emp_map,
    _proj_map,
):
    _, wk_groups, export_data = gantt_engine.generate_gantt_chart(
        start_of_week,
        zoom_factor,
        presentation_mode,
        data_version,
        _assignments_by_date,
        _leaves,
        _employees,
        _projects,
        _emp_map,
        _proj_map,
    )
    return wk_groups, export_data

wk_groups, export_data = get_cached_data(
    start_of_week,
    zoom_factor,
    presentation_mode,
    st.session_state.get("local_gantt_version", 0),
    st.session_state.assignments_by_date,
    st.session_state.leaves,
    st.session_state.employees,
    st.session_state.projects,
    st.session_state.emp_map,
    st.session_state.proj_map,
)

# Φτιάχνουμε απόλυτα ΜΟΝΑΔΙΚΑ IDs χρησιμοποιώντας HASH, αποκλείοντας συγκρούσεις!
safe_mapping = {}
key_to_safe_id = {}
for real_key in wk_groups.keys():
    safe_id = "bar_" + hashlib.md5(real_key.encode("utf-8")).hexdigest()
    safe_mapping[safe_id] = real_key
    key_to_safe_id[real_key] = safe_id

# --- NATIVE HTML GANTT CHART BUILDER ---
def build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id):
    timeline_width_px = int(2400 * zoom_factor)
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    BAR_HEIGHT_PX = 44
    LANE_STEP_PX = 46
    ROW_PAD_TOP_PX = 6
    ROW_PAD_BOTTOM_PX = 6
    TEXT_LINES = 4

    emp_short_names = {}
    external_crews = []
    for emp in st.session_state.employees:
        eid = emp["id"]
        full_name = emp["name"]
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name
        if emp.get("status", "Ενεργός") == "Ενεργός" and emp.get("is_external_crew", False):
            external_crews.append(emp)

    def is_on_leave_fast(eid, check_date):
        for l in st.session_state.leaves:
            if l["employeeId"] == eid and l["startDate"] <= check_date <= l["endDate"]:
                return True
        return False

    html = ""
    html += (
        "<div id='gantt-master-container' "
        "style='overflow: auto; height: 640px; position: relative; border: 4px solid #1e293b; border-radius: 12px; "
        "background: #ffffff; user-select: none; cursor: grab; "
        "box-shadow: 0px 12px 35px rgba(0,0,0,0.4); font-family: \"Segoe UI\", Tahoma, Geneva, Verdana, sans-serif;'>"
    )
    html += "<style>#gantt-master-container::-webkit-scrollbar { width: 12px; height: 12px; } #gantt-master-container::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 8px; } #gantt-master-container::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 8px; border: 3px solid #f1f5f9; } #gantt-master-container::-webkit-scrollbar-thumb:hover { background: #64748b; } .mygantt-bar:hover { transform: scale(1.02); z-index: 30 !important; box-shadow: 0 6px 12px rgba(0,0,0,0.3) !important; outline: 2px solid #1e293b !important; }</style>"
    html += "<div style='display: flex; position: sticky; top: 0; z-index: 100; background: #f8fafc; border-bottom: 3px solid #1e293b; min-width: max-content;'>"
    html += "<div style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 101; background: #f8fafc; border-right: 3px solid #1e293b; padding: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #1e293b; font-size: 14px;'>Ημέρα / Προσωπικό</div>"
    html += f"<div class='gantt-timeline-header' style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; height: 45px; background: #f8fafc;'>"

    for h in range(4, 25):
        pct = ((h - 4) / 20) * 100
        lbl = f"{h:02d}:00" if h < 24 else "00:00"
        html += f"<div style='position: absolute; left: {pct}%; height: 100%; border-left: 2px solid #94a3b8; padding-left: 4px; padding-top: 14px; font-weight: bold; font-size: 13px; color: #334155;'>{lbl}</div>"
    html += "</div></div>"

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"

        leaves_today = []
        for l in st.session_state.leaves:
            if l["startDate"] <= curr_date <= l["endDate"]:
                emp_n = emp_short_names.get(l["employeeId"], utils.get_employee_name(l["employeeId"]))
                sub_id = l.get("substituteId")
                if sub_id:
                    sub_n = emp_short_names.get(sub_id, utils.get_employee_name(sub_id))
                    leaves_today.append(f"{emp_n} (Αντ: {sub_n})")
                else:
                    leaves_today.append(f"{emp_n}")

        available_ext_crew = []
        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
        for emp in external_crews:
            eid = emp["id"]
            if not any(l["employeeId"] == eid and l["startDate"] <= curr_date <= l["endDate"] for l in st.session_state.leaves):
                is_busy_after_10 = any(
                    a.get("employeeId") == eid
                    and not a.get("is_cancelled", False)
                    and str(a.get("endTime", ""))[:5] > "10:00"
                    for a in day_assigns
                )
                if not is_busy_after_10:
                    available_ext_crew.append(emp_short_names.get(eid, emp["name"]))

        label_html = f"<div style='font-size: 14px; font-weight: bold; margin-bottom: 8px;'>🗓️ {day_str}</div>"
        if leaves_today:
            label_html += f"<div style='color: #d32f2f; margin-bottom: 8px; font-size: 11px;'><b>Άδειες:</b><br>{'<br>'.join(leaves_today)}</div>"
        if available_ext_crew:
            label_html += f"<div style='color: #0369a1; font-size: 11px;'><b>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:</b><br>{'<br>'.join(available_ext_crew)}</div>"

        day_groups = [g for g in wk_groups.values() if g["Date"] == curr_date]
        lanes = []
        group_lanes = []
        for g in sorted(day_groups, key=lambda x: x["StartTime"]):
            placed = False
            for idx, lane_end in enumerate(lanes):
                if g["StartTime"] >= lane_end:
                    lanes[idx] = g["EndTime"]
                    group_lanes.append((g, idx))
                    placed = True
                    break
            if not placed:
                lanes.append(g["EndTime"])
                group_lanes.append((g, len(lanes) - 1))

        row_height = max(1, len(lanes)) * LANE_STEP_PX + ROW_PAD_TOP_PX + ROW_PAD_BOTTOM_PX
        bg_color_row = "#eef2ff" if curr_date == get_local_today() else ("#f8fafc" if i % 2 == 1 else "#ffffff")

        html += f"<div style='display: flex; min-width: max-content; border-bottom: 2px solid #e2e8f0; background-color: {bg_color_row}; min-height: {row_height}px;'>"
        html += f"<div style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 50; background-color: {bg_color_row}; border-right: 3px solid #1e293b; padding: 10px; box-sizing: border-box;'>{label_html}</div>"
        html += f"<div style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; background-image: linear-gradient(to right, rgba(148, 163, 184, 0.3) 1px, transparent 1px); background-size: calc(100% / 20) 100%; padding-top: {ROW_PAD_TOP_PX}px; padding-bottom: {ROW_PAD_BOTTOM_PX}px;'>"

        for g, lane_idx in group_lanes:
            def t2p(t_str):
                h, m = map(int, t_str.split(":"))
                if h < 4:
                    h += 24
                mins = (h - 4) * 60 + m
                return max(0, min(100, (mins / 1200.0) * 100))

            left_pct = t2p(g["StartTime"])
            width_pct = t2p(g["EndTime"]) - left_pct
            top_px = lane_idx * LANE_STEP_PX + ROW_PAD_TOP_PX

            emps_str = ", ".join(g["Employees"]).upper()
            proj_name = g["Project"].upper()
            arr_str = f"[Προσ: {g['ArrivalTime']}] " if g["ArrivalTime"] else ""
            if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                emps_str = "⚠️ " + emps_str

            base_text = f"{arr_str}{g['StartTime']}-{g['EndTime']} | {proj_name} | {emps_str}"
            if g["Notes"]:
                base_text += f" ({g['Notes'].upper()})"
            if g["is_cancelled"]:
                base_text = f"<s>{base_text}</s>"
                if g["cancel_reason"]:
                    base_text += f"<br><span style='color:#dc2626;'>[{g['cancel_reason'].upper()}]</span>"

            bg_color = g["ColorHex"]
            tooltip = base_text.replace("<br>", " ").replace('"', "&quot;").replace("'", "&#39;")

            safe_id = key_to_safe_id.get(g["Key"], "")

            html += (
                f"<a href='javascript:void(0);' id='{safe_id}' draggable='false' class='mygantt-bar' "
                f"style='position: absolute; left: {left_pct}%; width: {width_pct}%; top: {top_px}px; "
                f"background-color: {bg_color}; height: {BAR_HEIGHT_PX}px; border: 1px solid rgba(0,0,0,0.5); border-radius: 6px; "
                f"box-shadow: 0 3px 6px rgba(0,0,0,0.15); display: flex; align-items: center; justify-content: center; "
                f"font-size: 11px; font-weight: bold; color: black; text-decoration: none; cursor: pointer; transition: all 0.1s; "
                f"box-sizing: border-box; overflow: hidden; z-index: 10; padding: 0; margin: 0; text-align: center;' title='{tooltip}'>"
                f"<div style='line-height: 1.15; pointer-events: none; width: 100%; padding: 0 4px; display: -webkit-box; "
                f"-webkit-line-clamp: {TEXT_LINES}; -webkit-box-orient: vertical; overflow: hidden;'>{base_text}</div></a>"
            )

        html += "</div></div>"
    html += "</div>"

    # --- JS Injector (Base64) ---
    js_code = """
    (function () {
      var s = document.getElementById('gantt-master-container');
      if (!s) return;

      if (window.ganttDragCleanup) {
        try { window.ganttDragCleanup(); } catch (e) {}
        window.ganttDragCleanup = null;
      }

      var savedScrollLeft = sessionStorage.getItem('ganttScrollLeft');
      var savedScrollTop = sessionStorage.getItem('ganttScrollTop');

      if (savedScrollLeft !== null) {
          s.scrollLeft = parseFloat(savedScrollLeft);
      } else {
          setTimeout(function(){ s.scrollLeft = s.scrollWidth * 0.10; }, 50);
      }

      if (savedScrollTop !== null) {
          s.scrollTop = parseFloat(savedScrollTop);
      }

      var isDown = false;
      var startX = 0;
      var scrollLeftStart = 0;
      var moved = false;
      var DRAG_THRESHOLD = 5;
      window.gIsDragging = false;

      function onScroll() {
        clearTimeout(onScroll._t);
        onScroll._t = setTimeout(function() {
          sessionStorage.setItem('ganttScrollLeft', String(s.scrollLeft));
          sessionStorage.setItem('ganttScrollTop', String(s.scrollTop));
        }, 100);
      }

      function startDrag(pageX) {
        isDown = true;
        moved = false;
        window.gIsDragging = false;
        startX = pageX - s.offsetLeft;
        scrollLeftStart = s.scrollLeft;
        s.style.cursor = 'grabbing';
        if (document.body) document.body.style.userSelect = 'none';
      }

      function moveDrag(pageX, ev) {
        if (!isDown) return;
        if (ev) ev.preventDefault();
        var walk = (pageX - s.offsetLeft) - startX;
        if (Math.abs(walk) > DRAG_THRESHOLD) {
          moved = true;
          window.gIsDragging = true;
        }
        s.scrollLeft = scrollLeftStart - walk * 1.5;
      }

      function endDrag() {
        if (!isDown) return;
        isDown = false;
        s.style.cursor = 'grab';
        if (document.body) document.body.style.userSelect = '';
        setTimeout(function(){ window.gIsDragging = false; }, 80);
      }

      function onMouseDown(e) {
        if (e.button !== 0) return;
        startDrag(e.pageX);
      }

      function onMouseMoveLocal(e) {
        moveDrag(e.pageX, e);
      }

      function onMouseMoveWin(e) {
        moveDrag(e.pageX, e);
      }

      function onMouseUp() {
        endDrag();
      }

      function onMouseLeave() {
        endDrag();
      }

      function onBlur() {
        endDrag();
      }

      function onTouchStart(e) {
        if (!e.touches || !e.touches[0]) return;
        isDown = true;
        moved = false;
        window.gIsDragging = false;
        startX = e.touches[0].pageX - s.offsetLeft;
        scrollLeftStart = s.scrollLeft;
      }

      function onTouchMove(e) {
        if (!isDown || !e.touches || !e.touches[0]) return;
        var walk = (e.touches[0].pageX - s.offsetLeft) - startX;
        if (Math.abs(walk) > DRAG_THRESHOLD) {
          moved = true;
          window.gIsDragging = true;
        }
        s.scrollLeft = scrollLeftStart - walk * 1.5;
      }

      function onTouchEnd() {
        endDrag();
      }

      function onDragStart(e) {
        e.preventDefault();
      }

      function onClickCapture(e) {
        var link = e.target.closest('a.mygantt-bar');
        if (link && (window.gIsDragging || moved)) {
          e.preventDefault();
          e.stopPropagation();
        }
      }

      s.addEventListener('scroll', onScroll);
      s.addEventListener('mousedown', onMouseDown, true);
      s.addEventListener('mousemove', onMouseMoveLocal, true);
      window.addEventListener('mousemove', onMouseMoveWin, true);
      s.addEventListener('mouseup', onMouseUp, true);
      s.addEventListener('mouseleave', onMouseLeave, true);
      window.addEventListener('mouseup', onMouseUp, true);
      window.addEventListener('blur', onBlur);

      s.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
      s.addEventListener('touchmove', onTouchMove, { passive: true, capture: true });
      s.addEventListener('touchend', onTouchEnd, { passive: true, capture: true });

      s.addEventListener('dragstart', onDragStart);
      document.addEventListener('click', onClickCapture, true);

      window.ganttDragCleanup = function () {
        s.removeEventListener('scroll', onScroll);
        s.removeEventListener('mousedown', onMouseDown, true);
        s.removeEventListener('mousemove', onMouseMoveLocal, true);

        window.removeEventListener('mousemove', onMouseMoveWin, true);
        s.removeEventListener('mouseup', onMouseUp, true);
        s.removeEventListener('mouseleave', onMouseLeave, true);
        window.removeEventListener('mouseup', onMouseUp, true);
        window.removeEventListener('blur', onBlur);

        s.removeEventListener('touchstart', onTouchStart, { capture: true });
        s.removeEventListener('touchmove', onTouchMove, { capture: true });
        s.removeEventListener('touchend', onTouchEnd, { capture: true });

        s.removeEventListener('dragstart', onDragStart);
        document.removeEventListener('click', onClickCapture, true);
      };
    })();
    """
    b64_js = base64.b64encode(js_code.encode("utf-8")).decode("utf-8")
    html += f"<img src='x' style='display:none;' onerror='eval(atob(\"{b64_js}\"))'>"

    return html

# --- ΕΜΦΑΝΙΣΗ ΚΑΙ ΕΝΤΟΠΙΣΜΟΣ ΚΛΙΚ ---
html_chart = build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id)
clicked_safe_id = click_detector(html_chart, key=f"gantt_detector_{st.session_state.detector_version}")

if clicked_safe_id:
    real_clicked_key = safe_mapping.get(clicked_safe_id, None)

    if clicked_safe_id != st.session_state.last_clicked_safe_id:
        st.session_state.last_clicked_safe_id = clicked_safe_id

        if real_clicked_key:
            st.session_state.clicked_key = real_clicked_key
            st.session_state.trigger_scroll = True
            st.rerun()

if st.session_state.get("clicked_key"):
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

# Κλήση του UI module για το Export Section
ui_dashboard.render_export_section(export_data, start_of_week)

# --- ΦΟΡΜΕΣ ΠΡΟΣΘΗΚΗΣ ΚΑΙ ΕΠΕΞΕΡΓΑΣΙΑΣ ΜΠΑΡΑΣ (Μέσω του ui_dashboard.py) ---
if not presentation_mode:
    st.divider()
    if is_full_admin:
        col_add, col_edit = st.columns(2)

        with col_add:
            # 1. Φόρμα Γρήγορης Προσθήκης
            qa_data = ui_dashboard.render_quick_add_form(selected_date, active_employee_ids)
            
            if qa_data:
                str_arrival = qa_data["t_arrival"].strftime("%H:%M") if qa_data["use_arr"] else ""
                str_start = qa_data["t_start"].strftime("%H:%M")
                str_end = qa_data["t_end"].strftime("%H:%M")

                if str_start >= str_end:
                    st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                else:
                    emps_to_process = qa_data["emp_choices"] if qa_data["emp_choices"] else [""]
                    new_assigns = []

                    if qa_data["custom_proj_name"].strip():
                        c_name = qa_data["custom_proj_name"].strip()
                        existing_p = next(
                            (p for p in st.session_state.projects if p["name"].strip().lower() == c_name.lower()),
                            None,
                        )
                        if existing_p:
                            final_proj_id = existing_p["id"]
                        else:
                            final_proj_id = str(uuid.uuid4())
                            new_p = {"id": final_proj_id, "name": c_name, "color": config.BASIC_COLORS[qa_data["color_choice"]]}
                            st.session_state.projects.append(new_p)
                            utils.db_insert("projects", new_p, track=False)
                    else:
                        final_proj_id = qa_data["proj_choice"]

                    for day_offset in range(qa_data["duration_days"]):
                        current_assign_date = qa_data["add_date"] + timedelta(days=day_offset)
                        valid_assignments = []

                        for eid in emps_to_process:
                            if eid:
                                emp_name = utils.get_employee_name(eid)
                                if scheduling.is_on_leave(eid, current_assign_date, st.session_state.leaves_by_emp):
                                    valid_assignments.append(
                                        {"eid": "", "start": str_start, "end": str_end, "msg": f"[Άδεια: {emp_name}]", "emp_name": emp_name}
                                    )
                                    st.toast(
                                        f"Ο/Η {emp_name} έχει άδεια στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.",
                                        icon="⚠️",
                                    )
                                else:
                                    day_assigns = st.session_state.assignments_by_date.get(current_assign_date, [])
                                    adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                        eid, str_start, str_end, day_assigns
                                    )
                                    if is_conflict:
                                        valid_assignments.append(
                                            {"eid": "", "start": str_start, "end": str_end, "msg": f"[Εμπλοκή: {emp_name}]", "emp_name": emp_name}
                                        )
                                        st.toast(
                                            f"Διπλοκράτηση {emp_name} στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.",
                                            icon="⚠️",
                                        )
                                    else:
                                        valid_assignments.append({"eid": eid, "start": adj_start, "end": adj_end, "msg": msg, "emp_name": emp_name})
                            else:
                                valid_assignments.append({"eid": "", "start": str_start, "end": str_end, "msg": "", "emp_name": ""})

                        for va in valid_assignments:
                            if va["msg"] == "Allowed Overlap":
                                st.toast(
                                    f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']} στις {current_assign_date.strftime('%d/%m')}.",
                                    icon="ℹ️",
                                )

                            c_notes = qa_data["add_notes"]
                            if va["msg"] and va["msg"] != "Allowed Overlap":
                                c_notes = f"{qa_data['add_notes']} {va['msg']}".strip()

                            new_assign = {
                                "id": str(uuid.uuid4()),
                                "employeeId": va["eid"],
                                "projectId": final_proj_id,
                                "date": current_assign_date,
                                "arrivalTime": str_arrival,
                                "startTime": va["start"],
                                "endTime": va["end"],
                                "colorName": qa_data["color_choice"],
                                "colorHex": config.BASIC_COLORS[qa_data["color_choice"]],
                                "notes": c_notes,
                                "is_cancelled": False,
                                "cancel_reason": "",
                                "recurring_id": None,
                            }
                            new_assigns.append(new_assign)
                            st.session_state.assignments.append(new_assign)

                    utils.db_insert("assignments", new_assigns, track=False)
                    st.success(f"Η ανάθεση ολοκληρώθηκε επιτυχώς για {qa_data['duration_days']} ημέρα/ες!")
                    time.sleep(0.4)
                    utils.mark_data_changed()
                    utils.init_data_and_sync()
                    st.session_state.qa_rc += 1
                    clear_bar_selection()
                    st.rerun()

        with col_edit:
            # Script για αυτόματο Scroll
            if st.session_state.get("trigger_scroll"):
                components.html(
                    f"""
                    <script>
                        setTimeout(function() {{
                            const headers = window.parent.document.querySelectorAll('h3');
                            for (let i = 0; i < headers.length; i++) {{
                                if(headers[i].innerText && headers[i].innerText.includes('Επεξεργασία Μπάρας')) {{
                                    headers[i].scrollIntoView({{behavior: 'smooth', block: 'start'}});
                                    break;
                                }}
                            }}
                        }}, 200);
                    </script>
                    """,
                    height=0,
                    width=0,
                )
                st.session_state.trigger_scroll = False

            # 2. Φόρμα Επεξεργασίας / Γρήγορης Μετακίνησης
            edit_data = ui_dashboard.render_edit_form(wk_groups, st.session_state.clicked_key, active_employee_ids)

            if edit_data:
                action = edit_data["action"]
                target_group = edit_data["target_group"]

                # Λογική: Γρήγορη Μετακίνηση (Με Fix για StopIteration)
                if action == "move":
                    delta_days = edit_data["delta_days"]
                    delta_hours = edit_data["delta_hours"]
                    has_error = False
                    new_assigns, old_assigns = [], []

                    for a_id in target_group["AssignmentIds"]:
                        # FIXED: Χρήση None fallback, αν η βάρδια έχει διαγραφεί από άλλον!
                        orig_a = next((a for a in st.session_state.assignments if a["id"] == a_id), None)
                        if not orig_a:
                            continue 
                            
                        new_a = dict(orig_a)
                        
                        if delta_days != 0:
                            new_a["date"] = orig_a["date"] + timedelta(days=delta_days)
                        if delta_hours != 0:
                            dummy_date = datetime(2000, 1, 1)
                            s_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["startTime"])[:5], "%H:%M").time())
                            e_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["endTime"])[:5], "%H:%M").time())
                            new_s_dt = s_dt + timedelta(hours=delta_hours)
                            new_e_dt = e_dt + timedelta(hours=delta_hours)
                            if new_s_dt.date() != dummy_date.date() or new_e_dt.date() != dummy_date.date():
                                st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας.")
                                has_error = True
                                break
                            new_a["startTime"] = new_s_dt.strftime("%H:%M")
                            new_a["endTime"] = new_e_dt.strftime("%H:%M")
                            if orig_a.get("arrivalTime"):
                                arr_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["arrivalTime"])[:5], "%H:%M").time())
                                new_a["arrivalTime"] = (arr_dt + timedelta(hours=delta_hours)).strftime("%H:%M")

                        if new_a["employeeId"]:
                            emp_name = utils.get_employee_name(new_a["employeeId"])
                            if scheduling.is_on_leave(new_a["employeeId"], new_a["date"], st.session_state.leaves_by_emp):
                                st.toast(f"Αδύνατη μετακίνηση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                                has_error = True
                                break

                            day_assigns = st.session_state.assignments_by_date.get(new_a["date"], [])
                            adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                new_a["employeeId"],
                                new_a["startTime"],
                                new_a["endTime"],
                                day_assigns,
                                exclude_ids=target_group["AssignmentIds"],
                            )
                            if is_conflict:
                                st.toast(f"Αδύνατη μετακίνηση: Διπλοκράτηση {emp_name}!", icon="⚠️")
                                has_error = True
                                break
                            new_a["startTime"], new_a["endTime"] = adj_start, adj_end
                            if msg == "Allowed Overlap":
                                st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου ({emp_name}).", icon="ℹ️")

                        old_assigns.append(orig_a)
                        new_assigns.append(new_a)

                    if not has_error and old_assigns:
                        for old_a, new_a in zip(old_assigns, new_assigns):
                            utils.db_update("assignments", new_a["id"], new_a, old_data=old_a, track=False)
                        st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                        st.session_state.assignments.extend(new_assigns)
                        clear_bar_selection()
                        st.rerun()

                # Λογική: Οριστική Διαγραφή
                elif action == "delete":
                    old_assigns = [a for a in st.session_state.assignments if a["id"] in target_group["AssignmentIds"]]
                    st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                    utils.db_delete_in("assignments", "id", target_group["AssignmentIds"], deleted_records=old_assigns)
                    clear_bar_selection()
                    st.rerun()

                # Λογική: Αποθήκευση Αλλαγών της Φόρμας Επεξεργασίας
                elif action == "edit":
                    str_arrival = edit_data["new_t_arrival"].strftime("%H:%M") if edit_data["use_arr_edit"] else ""
                    str_start = edit_data["new_t_start"].strftime("%H:%M")
                    str_end = edit_data["new_t_end"].strftime("%H:%M")
                    
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    else:
                        emps_to_process = edit_data["edit_emps"] if edit_data["edit_emps"] else [""]
                        valid_assignments = []
                        for eid in emps_to_process:
                            if eid:
                                emp_name = utils.get_employee_name(eid)
                                if scheduling.is_on_leave(eid, edit_data["edit_date"], st.session_state.leaves_by_emp):
                                    valid_assignments.append({"eid": "", "start": str_start, "end": str_end, "msg": f"[Άδεια: {emp_name}]", "emp_name": emp_name})
                                    st.toast(f"Ο/Η {emp_name} έχει άδεια. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                else:
                                    day_assigns = st.session_state.assignments_by_date.get(edit_data["edit_date"], [])
                                    adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                        eid, str_start, str_end, day_assigns, exclude_ids=target_group["AssignmentIds"]
                                    )
                                    if is_conflict:
                                        valid_assignments.append({"eid": "", "start": str_start, "end": str_end, "msg": f"[Εμπλοκή: {emp_name}]", "emp_name": emp_name})
                                        st.toast(f"Διπλοκράτηση {emp_name}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                    else:
                                        valid_assignments.append({"eid": eid, "start": adj_start, "end": adj_end, "msg": msg, "emp_name": emp_name})
                            else:
                                valid_assignments.append({"eid": "", "start": str_start, "end": str_end, "msg": "", "emp_name": ""})

                        if edit_data["edit_custom_proj_name"].strip():
                            c_name = edit_data["edit_custom_proj_name"].strip()
                            existing_p = next(
                                (p for p in st.session_state.projects if p["name"].strip().lower() == c_name.lower()),
                                None,
                            )
                            if existing_p:
                                final_edit_proj_id = existing_p["id"]
                            else:
                                final_edit_proj_id = str(uuid.uuid4())
                                new_p = {"id": final_edit_proj_id, "name": c_name, "color": config.BASIC_COLORS[edit_data["edit_color"]]}
                                st.session_state.projects.append(new_p)
                                utils.db_insert("projects", new_p, track=False)
                        else:
                            final_edit_proj_id = edit_data["edit_proj"]

                        old_assigns = [a for a in st.session_state.assignments if a["id"] in target_group["AssignmentIds"]]
                        st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                        utils.db_delete_in("assignments", "id", target_group["AssignmentIds"], deleted_records=old_assigns, track=False)

                        new_assigns = []
                        for va in valid_assignments:
                            if va["msg"] == "Allowed Overlap":
                                st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {va['emp_name']} ({va['start']})", icon="ℹ️")

                            c_notes = edit_data["edit_notes"]
                            if va["msg"] and va["msg"] != "Allowed Overlap":
                                c_notes = f"{edit_data['edit_notes']} {va['msg']}".strip()

                            new_a = {
                                "id": str(uuid.uuid4()),
                                "employeeId": va["eid"],
                                "projectId": final_edit_proj_id,
                                "date": edit_data["edit_date"],
                                "arrivalTime": str_arrival,
                                "startTime": va["start"],
                                "endTime": va["end"],
                                "colorName": edit_data["edit_color"],
                                "colorHex": config.BASIC_COLORS[edit_data["edit_color"]],
                                "notes": c_notes,
                                "is_cancelled": edit_data["e_is_cancelled"],
                                "cancel_reason": edit_data["e_cancel_reason"] if edit_data["e_is_cancelled"] else "",
                                "recurring_id": target_group.get("RecurringId"),
                            }
                            new_assigns.append(new_a)
                            st.session_state.assignments.append(new_a)
                            
                        utils.db_insert("assignments", new_assigns, track=False)
                        clear_bar_selection()
                        st.rerun()
