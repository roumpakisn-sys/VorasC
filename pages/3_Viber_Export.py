import streamlit as st
import pandas as pd
from datetime import datetime, date
import utils


# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

utils.init_data_and_sync()

# Φορτώνουμε το βασικό μενού στο πλάι (χωρίς τα υπο-μενού της Διαχείρισης)
utils.setup_shared_ui(show_menu=False)

# --- VIEW: VIBER EXPORT ---
st.title("📱 Ημερήσιο Πρόγραμμα (Viber)")
st.write("Δημιουργήστε το πρόγραμμα της ημέρας έτοιμο για αποστολή στο Viber.")

# ΚΡΙΣΙΜΟ AUTO-REFRESH: Βάζουμε αυτό το κρυφό flag για να σταματήσει το auto-polling
# να "κλέβει" τα κλικ στα checkboxes όσο είμαστε σε αυτή τη σελίδα.
st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

target_date = st.date_input("Επιλέξτε Ημερομηνία", value=date.today())


def _project_name(project_id):
    proj = utils.get_project_info(project_id)
    return proj.get("name", "Άγνωστο") if proj else "Άγνωστο"


def _employee_name(employee_id):
    return utils.get_employee_name(employee_id)


def _employee_viber_label(assignment, day_assignments):
    """
    Επιστρέφει το κείμενο εργαζομένου για Viber.

    Αν η βάρδια είναι συνέχεια/επικάλυψη μετά από άλλο έργο,
    εμφανίζεται όπως ζητήθηκε:
    ΜΕΤΑ ΑΠΟ 'ΟΝΟΜΑ ΕΡΓΟΥ' > ΟΝΟΜΑ ΕΡΓΑΖΟΜΕΝΟΥ

    Η λογική είναι αντίστοιχη με το Gantt:
    υπάρχει προηγούμενη βάρδια ίδιου εργαζομένου, άλλου έργου,
    που έχει αρχίσει πριν ή ίδια ώρα και τελειώνει μετά την έναρξη
    της τρέχουσας βάρδιας, ενώ η τρέχουσα τελειώνει μετά από εκείνη.
    """
    employee_id = assignment.get("employeeId")
    if not employee_id:
        return ""

    employee_name = _employee_name(employee_id)
    if not employee_name or employee_name == "Χωρίς Προσωπικό":
        return ""

    start_time = str(assignment.get("startTime", ""))[:5]
    end_time = str(assignment.get("endTime", ""))[:5]
    project_id = assignment.get("projectId")
    assignment_id = assignment.get("id")

    previous_assignments = []

    for other in day_assignments:
        if not isinstance(other, dict):
            continue

        if other.get("id") == assignment_id:
            continue

        if other.get("is_cancelled", False):
            continue

        if other.get("employeeId") != employee_id:
            continue

        other_project_id = other.get("projectId")
        if other_project_id == project_id:
            continue

        other_start = str(other.get("startTime", ""))[:5]
        other_end = str(other.get("endTime", ""))[:5]

        if (
            other_start <= start_time
            and other_end > start_time
            and end_time > other_end
        ):
            previous_assignments.append(other)

    if previous_assignments:
        previous_assignments.sort(
            key=lambda item: str(item.get("endTime", ""))[:5],
            reverse=True,
        )
        previous_project_name = _project_name(previous_assignments[0].get("projectId"))
        return f"ΜΕΤΑ ΑΠΟ '{previous_project_name}' > {employee_name}"

    return employee_name


# --- ΚΑΘΑΡΙΣΜΟΣ ΜΝΗΜΗΣ CHECKBOXES ΟΤΑΝ ΑΛΛΑΖΕΙ Η ΜΕΡΑ ---
# Αν ο χρήστης αλλάξει μέρα, θέλουμε όλα τα έργα να είναι ξανά προεπιλεγμένα (True).
if "viber_last_date" not in st.session_state or st.session_state.viber_last_date != target_date:
    st.session_state.viber_last_date = target_date
    for key in list(st.session_state.keys()):
        if key.startswith("chk_proj_"):
            del st.session_state[key]
    if "chk_include_leaves" in st.session_state:
        del st.session_state["chk_include_leaves"]

st.divider()

# 1. Συλλογή Δεδομένων για τη συγκεκριμένη ημέρα
day_assigns = [
    a for a in st.session_state.assignments
    if a.get("date") == target_date and not a.get("is_cancelled")
]

# Ταξινόμηση βάσει ώρας έναρξης
day_assigns.sort(key=lambda x: str(x.get("startTime", "23:59")))

# Εντοπισμός μοναδικών έργων της ημέρας
unique_projects = {}
for a in day_assigns:
    proj_id = a.get("projectId")
    if proj_id not in unique_projects:
        unique_projects[proj_id] = _project_name(proj_id)

selected_project_ids = []

# --- ΔΥΝΑΜΙΚΑ CHECKBOXES ΕΡΓΩΝ (Με Session State) ---
if unique_projects:
    st.markdown("#### ✅ Επιλογή Έργων προς Εξαγωγή")
    st.caption("Επιλέξτε ποια έργα θέλετε να συμπεριληφθούν στο τελικό μήνυμα.")

    # Αρχικοποίηση του state για να είναι όλα "Τσεκαρισμένα" by default
    for pid in unique_projects.keys():
        chk_key = f"chk_proj_{str(pid)}"
        if chk_key not in st.session_state:
            st.session_state[chk_key] = True

    if "chk_include_leaves" not in st.session_state:
        st.session_state["chk_include_leaves"] = True

    # Δημιουργία στηλών για ωραία εμφάνιση (μέχρι 4 στήλες)
    cols = st.columns(min(len(unique_projects), 4))

    for i, (pid, pname) in enumerate(unique_projects.items()):
        with cols[i % len(cols)]:
            # Το "key" διαβάζει και γράφει κατευθείαν στο st.session_state
            if st.checkbox(pname, key=f"chk_proj_{str(pid)}"):
                selected_project_ids.append(pid)

    st.write("")
    include_leaves = st.checkbox("🌴 Εμφάνιση Αδειών / Απουσιών στο τέλος", key="chk_include_leaves")
else:
    include_leaves = True

st.divider()

# Φιλτράρισμα των βαρδιών βάσει των επιλεγμένων έργων
filtered_assigns = [
    a for a in day_assigns
    if a.get("projectId") in selected_project_ids
]

groups = {}
for a in filtered_assigns:
    proj_name = _project_name(a.get("projectId"))
    emp_name = _employee_viber_label(a, day_assigns)
    start = str(a.get("startTime", ""))[:5]
    end = str(a.get("endTime", ""))[:5]
    arr = str(a.get("arrivalTime", ""))[:5]
    notes = a.get("notes", "")

    # Ομαδοποίηση ατόμων που είναι στο ίδιο έργο, την ίδια ώρα
    key = (start, end, proj_name, arr, notes)
    if key not in groups:
        groups[key] = []

    if emp_name and emp_name != "Χωρίς Προσωπικό":
        groups[key].append(emp_name)

day_leaves = [
    l for l in st.session_state.leaves
    if l.get("startDate") <= target_date <= l.get("endDate")
]

# 2. Χτίσιμο Αυτόματου Μηνύματος (Έτοιμο για Copy-Paste)
viber_msg = f"📅 *Πρόγραμμα Εργασιών - {target_date.strftime('%d/%m/%Y')}* 📅\n\n"

if not groups and not (day_leaves and include_leaves):
    viber_msg += "Δεν υπάρχουν προγραμματισμένες βάρδιες/άδειες (ή δεν έχει επιλεγεί κανένα έργο).\n"
else:
    if not groups and (day_leaves and include_leaves):
        viber_msg += "Δεν έχουν επιλεγεί/βρεθεί βάρδιες έργων.\n\n"

    for (start, end, proj, arr, notes), emps in groups.items():
        # Ώρες με αστερίσκους, έργο χωρίς αστερίσκους
        viber_msg += f"⏰ *{start} - {end}* | 🏗️ {proj}\n"

        # Ονόματα εργαζομένων με αστερίσκους
        emp_str = ", ".join(emps) if emps else "Χωρίς Προσωπικό"
        viber_msg += f"👥 Προσωπικό: *{emp_str}*\n"

        # Ώρα προσέλευσης (αν υπάρχει) με αστερίσκους
        if arr:
            viber_msg += f"🚶 Προσέλευση: *{arr}*\n"

        if notes:
            viber_msg += f"📝 Σημείωση: {notes}\n"
        viber_msg += "\n"

if day_leaves and include_leaves:
    viber_msg += "🌴 *Άδειες / Απουσίες*\n"
    for l in day_leaves:
        emp_name = _employee_name(l.get("employeeId"))
        sub = _employee_name(l.get("substituteId")) if l.get("substituteId") else ""
        if sub:
            viber_msg += f"🔸 {emp_name} (Αντικαταστάτης: {sub})\n"
        else:
            viber_msg += f"🔸 {emp_name}\n"

# Εμφάνιση Αποτελέσματος
st.subheader("🚀 Αυτόματο Μήνυμα (Γρήγορο)")
st.info("Το παρακάτω μήνυμα παράγεται αυτόματα και ανανεώνεται μόλις ξε-τικάρεις ένα έργο. Είναι έτοιμο για αντιγραφή.")
st.code(viber_msg, language="markdown")
