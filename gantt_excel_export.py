import io
import math
from datetime import datetime, timedelta

import streamlit as st


def _normalize_hex(color_value, default="999999"):
    raw = str(color_value or default).strip().replace("#", "")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raw = default
    return raw.upper()


def _time_to_minutes(time_value):
    raw = str(time_value or "00:00")[:5]
    hour, minute = map(int, raw.split(":"))
    if hour < 4:
        hour += 24
    return (hour - 4) * 60 + minute


def _slot_index(time_value, slot_minutes=30, mode="floor"):
    minutes = _time_to_minutes(time_value)
    if mode == "ceil":
        return int(math.ceil(minutes / slot_minutes))
    return int(math.floor(minutes / slot_minutes))


def _shorten_text(value, max_len=95):
    text = str(value or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _build_lanes(day_groups):
    """
    Ίδια βασική λογική στοίβαξης με το HTML Gantt:
    κάθε μπάρα μπαίνει στην πρώτη διαθέσιμη γραμμή που δεν επικαλύπτεται.
    """
    lanes = []
    placed = []

    for group in sorted(day_groups, key=lambda x: (x.get("StartTime", ""), x.get("EndTime", ""), x.get("Project", ""))):
        start = str(group.get("StartTime", ""))[:5]
        end = str(group.get("EndTime", ""))[:5]

        placed_lane = None
        for lane_idx, lane_end in enumerate(lanes):
            if start >= lane_end:
                lanes[lane_idx] = end
                placed_lane = lane_idx
                break

        if placed_lane is None:
            lanes.append(end)
            placed_lane = len(lanes) - 1

        placed.append((group, placed_lane))

    return placed, max(1, len(lanes))


def _apply_outer_border(ws, min_row, max_row, min_col, max_col, border):
    """
    Βάζει περίγραμμα γύρω/μέσα στο merged range.
    Στα merged cells το Excel συχνά δείχνει καλύτερα όταν όλα τα κελιά του range έχουν border.
    """
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            ws.cell(row=row, column=col).border = border


def create_visual_gantt_excel(wk_groups, start_of_week, slot_minutes=30):
    """
    Δημιουργεί Excel τύπου Gantt με συγχωνευμένα κελιά.

    Δεν αλλάζει δεδομένα.
    Παίρνει τα ήδη υπολογισμένα wk_groups της εβδομάδας.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except Exception as exc:
        raise RuntimeError("Λείπει το openpyxl από το περιβάλλον.") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Gantt"

    # Χρονικό εύρος όπως το HTML Gantt: 04:00 έως 00:00.
    start_hour = 4
    total_minutes = 20 * 60
    slot_count = total_minutes // slot_minutes
    first_time_col = 2
    last_time_col = first_time_col + slot_count - 1

    # Χρώματα/στυλ
    dark_fill = PatternFill("solid", fgColor="1E293B")
    header_fill = PatternFill("solid", fgColor="E2E8F0")
    day_fill = PatternFill("solid", fgColor="EEF2FF")
    white_fill = PatternFill("solid", fgColor="FFFFFF")
    grid_fill = PatternFill("solid", fgColor="F8FAFC")

    thin_gray = Side(style="thin", color="CBD5E1")
    medium_dark = Side(style="medium", color="1E293B")
    red_side = Side(style="medium", color="DC2626")
    black_side = Side(style="thin", color="222222")

    grid_border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)
    dark_border = Border(left=medium_dark, right=medium_dark, top=medium_dark, bottom=medium_dark)
    normal_bar_border = Border(left=black_side, right=black_side, top=black_side, bottom=black_side)
    general_bar_border = Border(left=red_side, right=red_side, top=red_side, bottom=red_side)

    # Τίτλος
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_time_col)
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = "Πρόγραμμα Gantt"
    title_cell.fill = dark_fill
    title_cell.font = Font(color="FFFFFF", bold=True, size=15)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_time_col)
    subtitle_cell = ws.cell(row=2, column=1)
    subtitle_cell.value = f"Εβδομάδα: {start_of_week.strftime('%d/%m/%Y')} - {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}"
    subtitle_cell.fill = white_fill
    subtitle_cell.font = Font(color="334155", bold=True, size=11)
    subtitle_cell.alignment = Alignment(horizontal="center", vertical="center")

    # Header ημέρα/ώρες
    ws.merge_cells(start_row=3, start_column=1, end_row=4, end_column=1)
    left_header = ws.cell(row=3, column=1)
    left_header.value = "Ημέρα / Προσωπικό"
    left_header.fill = header_fill
    left_header.font = Font(bold=True, color="1E293B")
    left_header.alignment = Alignment(horizontal="center", vertical="center")
    left_header.border = dark_border

    # Hour header merged ανά ώρα
    for hour_offset in range(20):
        col_start = first_time_col + (hour_offset * (60 // slot_minutes))
        col_end = col_start + (60 // slot_minutes) - 1
        label_hour = start_hour + hour_offset
        label = f"{label_hour:02d}:00" if label_hour < 24 else "00:00"

        ws.merge_cells(start_row=3, start_column=col_start, end_row=3, end_column=col_end)
        cell = ws.cell(row=3, column=col_start)
        cell.value = label
        cell.fill = header_fill
        cell.font = Font(bold=True, color="1E293B", size=9)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(col_start, col_end + 1):
            ws.cell(row=3, column=col).border = dark_border

    for slot in range(slot_count):
        col = first_time_col + slot
        minute_from_start = slot * slot_minutes
        hour = start_hour + (minute_from_start // 60)
        minute = minute_from_start % 60
        if hour >= 24:
            hour -= 24
        cell = ws.cell(row=4, column=col)
        cell.value = f"{hour:02d}:{minute:02d}"
        cell.fill = header_fill
        cell.font = Font(color="475569", size=7)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = grid_border

    # Διαστάσεις
    ws.column_dimensions["A"].width = 24
    for col in range(first_time_col, last_time_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = 4.2

    ws.row_dimensions[1].height = 25
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 20
    ws.row_dimensions[4].height = 18

    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    current_row = 5
    for day_idx in range(7):
        current_date = start_of_week + timedelta(days=day_idx)
        day_groups = [
            group for group in (wk_groups or {}).values()
            if group.get("Date") == current_date
        ]

        placed_groups, lane_count = _build_lanes(day_groups)
        day_start_row = current_row
        day_end_row = current_row + lane_count - 1

        # Αριστερό κελί ημέρας, merged κάθετα.
        ws.merge_cells(start_row=day_start_row, start_column=1, end_row=day_end_row, end_column=1)
        day_cell = ws.cell(row=day_start_row, column=1)
        day_cell.value = f"{day_names_gr[day_idx]}\n{current_date.strftime('%d/%m/%Y')}"
        day_cell.fill = day_fill
        day_cell.font = Font(bold=True, color="1E293B", size=10)
        day_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        _apply_outer_border(ws, day_start_row, day_end_row, 1, 1, dark_border)

        # Grid φόντου για όλες τις γραμμές της ημέρας.
        for row in range(day_start_row, day_end_row + 1):
            ws.row_dimensions[row].height = 34
            for col in range(first_time_col, last_time_col + 1):
                cell = ws.cell(row=row, column=col)
                cell.fill = grid_fill
                cell.border = grid_border

        # Μπάρες
        for group, lane_idx in placed_groups:
            row = day_start_row + lane_idx
            start_slot = _slot_index(group.get("StartTime"), slot_minutes=slot_minutes, mode="floor")
            end_slot = _slot_index(group.get("EndTime"), slot_minutes=slot_minutes, mode="ceil")

            start_slot = max(0, min(slot_count - 1, start_slot))
            end_slot = max(start_slot + 1, min(slot_count, end_slot))

            col_start = first_time_col + start_slot
            col_end = first_time_col + end_slot - 1

            project = str(group.get("Project", "")).upper()
            employees = ", ".join(group.get("Employees", [])).upper()
            notes = str(group.get("Notes", "") or "").upper()
            arrival = group.get("ArrivalTime", "")

            parts = []
            if arrival:
                parts.append(f"[Προσ: {arrival}]")
            parts.append(f"{group.get('StartTime')}-{group.get('EndTime')}")
            parts.append(project)
            if employees:
                parts.append(employees)
            if notes:
                parts.append(f"({notes})")

            bar_text = _shorten_text(" | ".join(parts), max_len=110)

            ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_end)
            bar_cell = ws.cell(row=row, column=col_start)
            bar_cell.value = bar_text
            bar_cell.fill = PatternFill("solid", fgColor=_normalize_hex(group.get("ColorHex")))
            bar_cell.font = Font(bold=True, color="FFFFFF", size=8)
            bar_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True, shrink_to_fit=True)

            is_general = bool(group.get("IsGeneral", False) or group.get("is_general", False))
            _apply_outer_border(
                ws,
                row,
                row,
                col_start,
                col_end,
                general_bar_border if is_general else normal_bar_border,
            )

        current_row = day_end_row + 1

    # Πάγωμα τίτλων/headers.
    ws.freeze_panes = "B5"

    # Print / view setup
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def render_visual_gantt_excel_export(wk_groups, start_of_week):
    """Κουμπί εξαγωγής οπτικού Gantt σε Excel με συγχωνευμένα κελιά."""
    if not wk_groups:
        return

    try:
        data = create_visual_gantt_excel(wk_groups, start_of_week)
    except Exception as exc:
        st.warning(f"Δεν ήταν δυνατή η δημιουργία του οπτικού Excel Gantt: {exc}")
        return

    st.download_button(
        label="📊 Εξαγωγή Gantt σε Excel με μπάρες",
        data=data,
        file_name=f"Gantt_Bars_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
