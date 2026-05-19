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
st.title("📱 Ημερήσιο Πρόγραμμα (Viber & AI)")
st.write("Δημιουργήστε το πρόγραμμα της ημέρας έτοιμο για αποστολή στο Viber.")

target_date = st.date_input("Επιλέξτε Ημερομηνία", value=date.today())
st.divider()

# 1. Συλλογή Δεδομένων για τη συγκεκριμένη ημέρα
day_assigns = [a for a in st.session_state.assignments if a.get('date') == target_date and not a.get('is_cancelled')]
# Ταξινόμηση βάσει ώρας έναρξης
day_assigns.sort(key=lambda x: str(x.get('startTime', '23:59')))

groups = {}
for a in day_assigns:
    proj = utils.get_project_info(a.get('projectId'))
    proj_name = proj.get('name', "Άγνωστο") if proj else "Άγνωστο"
    emp_name = utils.get_employee_name(a.get('employeeId'))
    start = str(a.get('startTime', ''))[:5]
    end = str(a.get('endTime', ''))[:5]
    arr = str(a.get('arrivalTime', ''))[:5]
    notes = a.get('notes', '')
    
    # Ομαδοποίηση ατόμων που είναι στο ίδιο έργο, την ίδια ώρα
    key = (start, end, proj_name, arr, notes)
    if key not in groups:
        groups[key] = []
    if emp_name and emp_name != "Χωρίς Προσωπικό":
        groups[key].append(emp_name)
        
day_leaves = [l for l in st.session_state.leaves if l.get('startDate') <= target_date <= l.get('endDate')]

# 2. Χτίσιμο Αυτόματου Μηνύματος (Έτοιμο για Copy-Paste)
viber_msg = f"📅 *Πρόγραμμα Εργασιών - {target_date.strftime('%d/%m/%Y')}* 📅\n\n"

if not groups:
    viber_msg += "Δεν υπάρχουν προγραμματισμένες βάρδιες για αυτή την ημέρα.\n"
else:
    for (start, end, proj, arr, notes), emps in groups.items():
        viber_msg += f"⏰ *{start} - {end}* | 🏗️ *{proj}*\n"
        emp_str = ", ".join(emps) if emps else "Χωρίς Προσωπικό"
        viber_msg += f"👥 Προσωπικό: {emp_str}\n"
        if arr: viber_msg += f"🚶 Προσέλευση: {arr}\n"
        if notes: viber_msg += f"📝 Σημείωση: {notes}\n"
        viber_msg += "\n"
        
if day_leaves:
    viber_msg += "🌴 *Άδειες / Απουσίες*\n"
    for l in day_leaves:
        emp_name = utils.get_employee_name(l.get('employeeId'))
        sub = utils.get_employee_name(l.get('substituteId')) if l.get('substituteId') else ""
        if sub:
            viber_msg += f"🔸 {emp_name} (Αντικαταστάτης: {sub})\n"
        else:
            viber_msg += f"🔸 {emp_name}\n"
            
# 3. Χτίσιμο Αιτήματος (Prompt) για το AI
ai_prompt = f"Φτιάξε ένα όμορφο, φιλικό και επαγγελματικό μήνυμα για το Viber, με το ημερήσιο πρόγραμμα εργασιών για τις {target_date.strftime('%d/%m/%Y')}. Χρησιμοποίησε emojis. Βάλε τις εργασίες με χρονολογική σειρά.\n\nΔεδομένα εργασιών:\n"
for (start, end, proj, arr, notes), emps in groups.items():
    emp_str = ", ".join(emps) if emps else "Κανένας"
    ai_prompt += f"- Ώρα: {start}-{end}, Έργο: {proj}, Άτομα: {emp_str}"
    if arr: ai_prompt += f", Προσέλευση: {arr}"
    if notes: ai_prompt += f", Σημειώσεις: {notes}"
    ai_prompt += "\n"
if day_leaves:
    ai_prompt += "\nΆδειες:\n"
    for l in day_leaves:
        ai_prompt += f"- {utils.get_employee_name(l['employeeId'])}\n"

# Εμφάνιση Καρτελών
tab_auto, tab_ai = st.tabs(["🚀 Αυτόματο Μήνυμα (Γρήγορο)", "🤖 Δημιουργία με AI (ChatGPT)"])

with tab_auto:
    st.info("Το παρακάτω μήνυμα παράγεται αυτόματα και είναι έτοιμο για αντιγραφή. Κάντε κλικ στο εικονίδιο αντιγραφής επάνω δεξιά στο πλαίσιο.")
    st.code(viber_msg, language="markdown")
    
with tab_ai:
    st.subheader("📝 Χειροκίνητη Αντιγραφή (Prompt)")
    st.info("Αν προτιμάτε να χρησιμοποιήσετε το **δικό σας ChatGPT** για ένα πιο προσαρμοσμένο κείμενο, αντιγράψτε το παρακάτω κείμενο (με το εικονίδιο επάνω δεξιά) και κάντε το επικόλληση εκεί.")
    st.code(ai_prompt, language="text")
