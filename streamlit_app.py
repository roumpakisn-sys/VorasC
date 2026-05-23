# streamlit_app.py
import streamlit as st

# ΠΡΕΠΕΙ να είναι η πρώτη εντολή Streamlit
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

import utils

# --- ΑΡΧΙΚΟΠΟΙΗΣΗ ΒΑΣΙΚΩΝ ΜΕΤΑΒΛΗΤΩΝ (Για ασφαλή λειτουργία Εκτός Σύνδεσης) ---
if "employees" not in st.session_state: st.session_state.employees = []
if "projects" not in st.session_state: st.session_state.projects = []
if "assignments" not in st.session_state: st.session_state.assignments = []
if "leaves" not in st.session_state: st.session_state.leaves = []
if "recurring_patterns" not in st.session_state: st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state: st.session_state.evaluations = []

# --- ΟΘΟΝΗ ΣΥΝΔΕΣΗΣ (AUTHENTICATION) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🛡️ Staff Manager Pro</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Παρακαλώ επιλέξτε χρήστη και εισάγετε τον κωδικό πρόσβασης.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            users_list = ["Admin", "EXOU", "MEMEK", "NAK", "PAP", "TAN"]
            username = st.selectbox("Χρήστης", users_list)
            
            password = st.text_input("Κωδικός Πρόσβασης", type="password")
            submit = st.form_submit_button("Είσοδος", use_container_width=True)
            
            if submit:
                # 1. Θέτουμε αρχικά τους προεπιλεγμένους κωδικούς (Fallback για τοπική χρήση)
                valid_passwords = {
                    "Admin": "admin123",
                    "EXOU": "pass1",
                    "MEMEK": "pass2",
                    "NAK": "pass3",
                    "PAP": "pass4",
                    "TAN": "pass5"
                }
                
                # 2. ΑΛΕΞΙΣΦΑΙΡΗ ΛΟΓΙΚΗ ΓΙΑ ΤΑ SECRETS (Cloud)
                try:
                    if hasattr(st, "secrets"):
                        if "APP_PASSWORD" in st.secrets: valid_passwords["Admin"] = st.secrets["APP_PASSWORD"]
                        if "USER1_PASSWORD" in st.secrets: valid_passwords["EXOU"] = st.secrets["USER1_PASSWORD"]
                        if "USER2_PASSWORD" in st.secrets: valid_passwords["MEMEK"] = st.secrets["USER2_PASSWORD"]
                        if "USER3_PASSWORD" in st.secrets: valid_passwords["NAK"] = st.secrets["USER3_PASSWORD"]
                        if "USER4_PASSWORD" in st.secrets: valid_passwords["PAP"] = st.secrets["USER4_PASSWORD"]
                        if "USER5_PASSWORD" in st.secrets: valid_passwords["TAN"] = st.secrets["USER5_PASSWORD"]
                except BaseException:
                    pass
                
                if password == valid_passwords.get(username):
                    st.session_state.authenticated = True
                    st.session_state.current_user = username
                    # Force background auto-refresh state στο login,
                    # ώστε ο χρήστης να ξεκινάει πάντα με φρέσκα δεδομένα.
                    st.session_state.last_sync_time = None
                    st.session_state.global_db_ts = "force_refresh"
                    st.session_state.last_processed_version = -1
                    st.session_state.data_dirty = True
                    st.session_state.force_full_sync_once = True
                    st.switch_page("pages/1_Gantt_Dashboard.py")
                else:
                    st.error("Λάθος κωδικός πρόσβασης. Δοκιμάστε ξανά.")
else:
    # Ασφάλεια συγχρονισμού: κάθε redirect από login page σε dashboard
    # ζητάει ένα πλήρες refresh δεδομένων μία φορά στο νέο session context.
    st.session_state.last_sync_time = None
    st.session_state.global_db_ts = "force_refresh"
    st.session_state.last_processed_version = -1
    st.session_state.data_dirty = True
    st.session_state.force_full_sync_once = True
    st.switch_page("pages/1_Gantt_Dashboard.py")
