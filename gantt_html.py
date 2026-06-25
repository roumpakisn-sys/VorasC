import base64
import html as html_utils
from datetime import datetime, timedelta

import streamlit as st

import config
import utils


def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()


def build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id, gantt_height_px):
    timeline_width_px = int(2400 * zoom_factor)
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    # Ψηλότερες μπάρες + μικρότερα κενά
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
        f"style='overflow: auto; height: {gantt_height_px}px; min-height: 360px; width: 100%; max-width: 100%; position: relative; border: 4px solid #1e293b; border-radius: 12px; "
        "background: #ffffff; user-select: none; cursor: grab; "
        "box-shadow: 0px 12px 35px rgba(0,0,0,0.4); font-family: \"Segoe UI\", Tahoma, Geneva, Verdana, sans-serif;'>"
    )

    html += "<style>#gantt-master-container::-webkit-scrollbar { width: 12px; height: 12px; } #gantt-master-container::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 8px; } #gantt-master-container::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 8px; border: 3px solid #f1f5f9; } #gantt-master-container::-webkit-scrollbar-thumb:hover { background: #64748b; } .mygantt-bar:hover { transform: scale(1.02); z-index: 30 !important; box-shadow: 0 6px 12px rgba(0,0,0,0.3) !important; outline: 2px solid #1e293b !important; } .gantt-copy-project-btn { position:absolute; top:2px; right:2px; width:18px; height:18px; border:1px solid rgba(255,255,255,0.75); border-radius:5px; background:rgba(15,23,42,0.78); color:#ffffff; font-size:11px; line-height:16px; padding:0; margin:0; z-index:50; cursor:pointer; pointer-events:auto; display:flex; align-items:center; justify-content:center; box-shadow:0 1px 3px rgba(0,0,0,0.35); } .gantt-copy-project-btn:hover { background:rgba(220,38,38,0.92); transform:scale(1.08); }</style>"

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

        available_after_6 = []
        available_after_10 = []
        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
        for emp in external_crews:
            eid = emp["id"]
            if any(l["employeeId"] == eid and l["startDate"] <= curr_date <= l["endDate"] for l in st.session_state.leaves):
                continue

            emp_label = emp_short_names.get(eid, emp["name"])

            is_busy_after_6 = any(
                a.get("employeeId") == eid
                and not a.get("is_cancelled", False)
                and str(a.get("endTime", ""))[:5] > "06:00"
                for a in day_assigns
            )

            is_busy_after_10 = any(
                a.get("employeeId") == eid
                and not a.get("is_cancelled", False)
                and str(a.get("endTime", ""))[:5] > "10:00"
                for a in day_assigns
            )

            # Δύο κατηγορίες:
            # 1) ΔΙΑΘΕΣΙΜΟΙ: ελεύθεροι μετά τις 06:00.
            # 2) ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ: έχουν τελειώσει πρωινή απασχόληση μέχρι τις 10:00.
            # Δεν βάζουμε το ίδιο άτομο και στις δύο λίστες.
            if not is_busy_after_6:
                available_after_6.append(emp_label)
            elif not is_busy_after_10:
                available_after_10.append(emp_label)

        label_html = f"<div style='font-size: 14px; font-weight: bold; margin-bottom: 8px;'>🗓️ {day_str}</div>"
        if leaves_today:
            label_html += f"<div style='color: #d32f2f; margin-bottom: 8px; font-size: 11px;'><b>Άδειες:</b><br>{'<br>'.join(leaves_today)}</div>"
        if available_after_6:
            label_html += f"<div style='color: #15803d; margin-bottom: 8px; font-size: 11px;'><b>ΔΙΑΘΕΣΙΜΟΙ:</b><br>{'<br>'.join(available_after_6)}</div>"
        if available_after_10:
            label_html += f"<div style='color: #0369a1; font-size: 11px;'><b>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:</b><br>{'<br>'.join(available_after_10)}</div>"

        day_groups = [g for g in wk_groups.values() if g["Date"] == curr_date]

        # Οι μπλε μπάρες μπαίνουν πάντα κάτω από όλες τις άλλες μπάρες της ημέρας.
        # Δεν αλλάζει η αποθήκευση ούτε η λογική των βαρδιών· μόνο η οπτική στοίβαξη.
        blue_stack_hex = config.BLUE_STACK_HEX.lower()
        non_blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() != blue_stack_hex]
        blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() == blue_stack_hex]

        group_lanes = []

        non_blue_lanes = []
        for g in sorted(non_blue_groups, key=lambda x: x["StartTime"]):
            placed = False
            for idx, lane_end in enumerate(non_blue_lanes):
                if g["StartTime"] >= lane_end:
                    non_blue_lanes[idx] = g["EndTime"]
                    group_lanes.append((g, idx))
                    placed = True
                    break
            if not placed:
                non_blue_lanes.append(g["EndTime"])
                group_lanes.append((g, len(non_blue_lanes) - 1))

        blue_lanes = []
        blue_lane_offset = len(non_blue_lanes)
        for g in sorted(blue_groups, key=lambda x: x["StartTime"]):
            placed = False
            for idx, lane_end in enumerate(blue_lanes):
                if g["StartTime"] >= lane_end:
                    blue_lanes[idx] = g["EndTime"]
                    group_lanes.append((g, blue_lane_offset + idx))
                    placed = True
                    break
            if not placed:
                blue_lanes.append(g["EndTime"])
                group_lanes.append((g, blue_lane_offset + len(blue_lanes) - 1))

        total_lanes = len(non_blue_lanes) + len(blue_lanes)
        row_height = max(1, total_lanes) * LANE_STEP_PX + ROW_PAD_TOP_PX + ROW_PAD_BOTTOM_PX
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

            def _employee_text_html(employee_name):
                """
                Μορφοποίηση μόνο του ονόματος εργαζόμενου μέσα στη μπάρα.
                - Κανονικά ονόματα: λευκά γράμματα.
                - Ένδειξη [ΜΕΤΑ ΑΠΟ ...]: κόκκινη ένδειξη, λευκό το όνομα.
                Δεν αλλάζει δεδομένα ή λογική, μόνο HTML εμφάνιση.
                """
                text_value = str(employee_name or "").upper().strip()
                escaped_value = html_utils.escape(text_value)

                if text_value.startswith("[ΜΕΤΑ ΑΠΟ ") and "▶" in text_value:
                    before_arrow, after_arrow = text_value.split("▶", 1)
                    after_arrow = after_arrow.strip()
                    closing = ""
                    if after_arrow.endswith("]"):
                        after_arrow = after_arrow[:-1].strip()
                        closing = "]"

                    red_part = html_utils.escape(before_arrow.strip() + " ▶")
                    white_name = html_utils.escape(after_arrow)
                    red_closing = html_utils.escape(closing)

                    return (
                        "<span style='color:#dc2626; font-weight:900;'>"
                        + red_part
                        + " </span>"
                        + "<span style='color:#ffffff; font-weight:900; text-shadow:0 1px 2px rgba(0,0,0,0.55);'>"
                        + white_name
                        + "</span>"
                        + "<span style='color:#dc2626; font-weight:900;'>"
                        + red_closing
                        + "</span>"
                    )

                return (
                    "<span style='color:#ffffff; font-weight:900; text-shadow:0 1px 2px rgba(0,0,0,0.55);'>"
                    + escaped_value
                    + "</span>"
                )

            def _group_employee_labels(employee_names):
                """
                Ομαδοποιεί εργαζόμενους που έχουν ίδια ένδειξη:
                [ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' ▶ ΟΝΟΜΑ]
                ώστε να εμφανίζονται ως:
                [ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' ▶ ΟΝΟΜΑ1, ΟΝΟΜΑ2]
                """
                grouped_after = {}
                normal_names = []

                for raw_name in employee_names or []:
                    text_value = str(raw_name or "").upper().strip()

                    if text_value.startswith("[ΜΕΤΑ ΑΠΟ ") and "▶" in text_value:
                        before_arrow, after_arrow = text_value.split("▶", 1)
                        after_arrow = after_arrow.strip()

                        if after_arrow.endswith("]"):
                            after_arrow = after_arrow[:-1].strip()

                        prefix = before_arrow.strip()
                        grouped_after.setdefault(prefix, [])
                        if after_arrow and after_arrow not in grouped_after[prefix]:
                            grouped_after[prefix].append(after_arrow)
                    else:
                        if text_value and text_value not in normal_names:
                            normal_names.append(text_value)

                result = list(normal_names)

                for prefix, names in grouped_after.items():
                    if names:
                        result.append(f"{prefix} ▶ {', '.join(names)}]")

                return result

            grouped_employee_labels = _group_employee_labels(g["Employees"])
            emps_plain = ", ".join(grouped_employee_labels).upper()
            emps_html = ", ".join(_employee_text_html(emp) for emp in grouped_employee_labels)
            proj_name = g["Project"].upper()
            arr_str = f"[Προσ: {g['ArrivalTime']}] " if g["ArrivalTime"] else ""

            if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_plain:
                emps_plain = "⚠️ " + emps_plain
                emps_html = "⚠️ " + emps_html

            base_text_plain = f"{arr_str}{g['StartTime']}-{g['EndTime']} | {proj_name} | {emps_plain}"
            base_text = (
                f"{html_utils.escape(arr_str)}{g['StartTime']}-{g['EndTime']} | "
                f"{html_utils.escape(proj_name)} | {emps_html}"
            )

            if g["Notes"]:
                notes_upper = g["Notes"].upper()
                base_text_plain += f" ({notes_upper})"
                base_text += f" ({html_utils.escape(notes_upper)})"

            if g["is_cancelled"]:
                base_text = f"<s>{base_text}</s>"
                if g["cancel_reason"]:
                    cancel_reason_upper = g["cancel_reason"].upper()
                    base_text_plain += f" [{cancel_reason_upper}]"
                    base_text += f"<br><span style='color:#dc2626;'>[{html_utils.escape(cancel_reason_upper)}]</span>"

            bg_color = g["ColorHex"]
            tooltip = base_text_plain.replace('"', "&quot;").replace("'", "&#39;")
            project_copy_attr = html_utils.escape(str(g["Project"]), quote=True)

            # Κόκκινη περιμετρική ένδειξη για μπάρες που έχουν τικαριστεί ως "Γενικός".
            # Χρησιμοποιούμε border + outline + inset box-shadow, ώστε να φαίνεται καθαρά
            # πάνω σε οποιοδήποτε χρώμα μπάρας. Δεν αλλάζει λειτουργία ή δεδομένα.
            is_general_bar = bool(g.get("IsGeneral", False) or g.get("is_general", False))
            bar_border = "3px solid #dc2626" if is_general_bar else "1px solid rgba(0,0,0,0.5)"
            bar_outline = "3px solid #dc2626" if is_general_bar else "none"
            bar_outline_offset = "-3px" if is_general_bar else "0"
            bar_shadow = (
                "inset 0 0 0 3px #dc2626, 0 0 0 2px rgba(220,38,38,0.55), 0 3px 8px rgba(0,0,0,0.25)"
                if is_general_bar
                else "0 3px 6px rgba(0,0,0,0.15)"
            )

            safe_id = key_to_safe_id.get(g["Key"], "")

            html += (
                f"<a href='javascript:void(0);' id='{safe_id}' draggable='false' class='mygantt-bar' "
                f"style='position: absolute; left: {left_pct}%; width: {width_pct}%; top: {top_px}px; "
                f"background-color: {bg_color}; height: {BAR_HEIGHT_PX}px; border: {bar_border}; border-radius: 6px; "
                f"box-shadow: {bar_shadow}; outline: {bar_outline}; outline-offset: {bar_outline_offset}; display: flex; align-items: center; justify-content: center; "
                f"font-size: 11px; font-weight: bold; color: black; text-decoration: none; cursor: pointer; transition: all 0.1s; "
                f"box-sizing: border-box; overflow: hidden; z-index: 10; padding: 0; margin: 0; text-align: center;' title='{tooltip}'>"
                f"<button type='button' class='gantt-copy-project-btn' data-project='{project_copy_attr}' title='Αντιγραφή ονόματος έργου'>📋</button>"
                f"<div style='line-height: 1.15; pointer-events: none; width: 100%; padding: 0 22px 0 4px; display: -webkit-box; "
                f"-webkit-line-clamp: {TEXT_LINES}; -webkit-box-orient: vertical; overflow: hidden;'>{base_text}</div></a>"
            )

        html += "</div></div>"

    html += "</div>"

    # --- JS Injector (Base64) ---
    # FIX: σε κάθε rerun κάνουμε cleanup παλιών listeners και ξαναδένουμε στο νέο gantt element.
    # Επίσης κρατάμε και vertical θέση (scrollTop), όχι μόνο horizontal.
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
        if (isCopyProjectButtonTarget(e)) return;
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

      function copyTextToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
          return navigator.clipboard.writeText(text);
        }

        return new Promise(function(resolve, reject) {
          try {
            var textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            textarea.style.top = '-9999px';
            document.body.appendChild(textarea);
            textarea.select();
            var ok = document.execCommand('copy');
            document.body.removeChild(textarea);
            if (ok) resolve();
            else reject(new Error('copy command failed'));
          } catch (err) {
            reject(err);
          }
        });
      }

      function flashCopyButton(btn, ok) {
        if (!btn) return;
        var oldText = btn.textContent;
        btn.textContent = ok ? '✓' : '!';
        setTimeout(function() {
          btn.textContent = oldText || '📋';
        }, 900);
      }

      function handleProjectCopy(btn) {
        var projectName = btn.getAttribute('data-project') || '';
        if (!projectName) return;

        copyTextToClipboard(projectName).then(function() {
          flashCopyButton(btn, true);
        }).catch(function() {
          flashCopyButton(btn, false);
        });
      }

      function isCopyProjectButtonTarget(e) {
        return e && e.target && e.target.closest && e.target.closest('.gantt-copy-project-btn');
      }

      function onClickCapture(e) {
        var copyBtn = isCopyProjectButtonTarget(e);
        if (copyBtn) {
          e.preventDefault();
          e.stopPropagation();
          handleProjectCopy(copyBtn);
          return;
        }

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
