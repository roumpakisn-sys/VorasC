import streamlit as st

# ΠΡΕΠΕΙ να είναι η πρώτη εντολή Streamlit
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

import utils

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
            username = st.selectbox("Χρήστης", ["Admin", "EXOUZ", "MEMEK", "NAK", "TAN"])
            password = st.text_input("Κωδικός Πρόσβασης", type="password")
            submit = st.form_submit_button("Είσοδος", use_container_width=True)
            
            if submit:
                valid_passwords = {
                    "Admin": st.secrets.get("APP_PASSWORD", "admin123"),
                    "EXOUZ": st.secrets.get("USER1_PASSWORD", "pass1"),
                    "MEMEK": st.secrets.get("USER2_PASSWORD", "pass2"),
                    "NAK": st.secrets.get("USER3_PASSWORD", "pass3"),
                    "TAN": st.secrets.get("USER4_PASSWORD", "pass4")
                }
                
                if password == valid_passwords.get(username):
                    st.session_state.authenticated = True
                    st.session_state.current_user = username
                    st.switch_page("pages/1_Gantt_Dashboard.py")
                else:
                    st.error("Λάθος κωδικός πρόσβασης. Δοκιμάστε ξανά.")
else:
    # Αν είναι ήδη συνδεδεμένος, προώθηση στο Dashboard
    st.switch_page("pages/1_Gantt_Dashboard.py")
