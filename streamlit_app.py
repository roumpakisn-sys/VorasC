import streamlit as st
import database as db
import time

# ==========================================
# 1. ΡΥΘΜΙΣΗ ΣΕΛΙΔΑΣ (Πρέπει να είναι η 1η εντολή)
# ==========================================
st.set_page_config(page_title="Staff Manager Pro", page_icon="🏢", layout="wide")

# Αρχικοποίηση μεταβλητών μνήμης από τη βάση (database.py)
db.init_session_state()

# ==========================================
# 2. ΕΞΥΠΝΟΣ ΣΥΓΧΡΟΝΙΣΜΟΣ (SMART POLLING)
# ==========================================
# Το fragment αυτό τρέχει αόρατα στο παρασκήνιο κάθε 15 δευτερόλεπτα.
# ΔΕΝ κάνει refresh όλη τη σελίδα, άρα δεν διακόπτει την εργασία σου!
@st.fragment(run_every=15)
def background_sync():
    if st.session_state.get('current_user'):
        latest_db_ts = db.get_latest_activity_timestamp()
        
        # Αν κάποιος άλλος χρήστης έκανε μια αλλαγή στη Supabase...
        if latest_db_ts and latest_db_ts != st.session_state.global_db_ts:
            st.session_state.global_db_ts = latest_db_ts
            # Καθαρίζουμε την προσωρινή μνήμη. 
            # Στο επόμενο κλικ, η εφαρμογή θα τραβήξει ακαριαία τα νέα δεδομένα!
            db.fetch_paginated.clear()

# ==========================================
# 3. ΣΥΣΤΗΜΑ ΕΙΣΟΔΟΥ (LOGIN)
# ==========================================
if not st.session_state.current_user:
    # Αν ο χρήστης δεν έχει κάνει Login, κρύβουμε το μενού
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none; }
        </style>
    """, unsafe_allow_html=True)
    
    st.title("🔐 Είσοδος στο Σύστημα")
    
    # Φόρμα Σύνδεσης
    with st.form("login_form"):
        st.write("Παρακαλώ συνδεθείτε για να συνεχίσετε")
        username = st.text_input("Όνομα Χρήστη (π.χ. admin)")
        password = st.text_input("Κωδικός", type="password")
        role = st.selectbox("Ρόλος", ["Admin", "User"])
        submit = st.form_submit_button("Σύνδεση")
        
        if submit:
            # ΣΗΜΕΙΩΣΗ: Εδώ μπορείς να αλλάξεις τους κωδικούς!
            if username == "admin" and password == "1234": 
                db.login_user(username, role)
                st.success("Επιτυχής σύνδεση! Παρακαλώ περιμένετε...")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Λάθος όνομα χρήστη ή κωδικός.")

# ==========================================
# 4. ΑΡΧΙΚΗ ΟΘΟΝΗ (ΜΕΤΑ ΤΟ LOGIN)
# ==========================================
else:
    # Εμφάνιση στοιχείων χρήστη στο Sidebar
    st.sidebar.title(f"👤 {st.session_state.current_user}")
    st.sidebar.info(f"Ρόλος: {st.session_state.user_role}")
    
    if st.sidebar.button("Αποσύνδεση"):
        db.logout_user()
        
    st.title("Καλώς ήρθατε στο Staff Manager Pro! 👋")
    st.write("---")
    st.info("👈 Επιλέξτε μια από τις καρτέλες στο **μενού αριστερά** για να διαχειριστείτε το Προσωπικό, τις Βάρδιες και τα Έργα.")
    st.success("✅ Ο συγχρονισμός παρασκηνίου είναι ενεργός. Η εφαρμογή είναι πλέον ελαφριά και ανταποκρίνεται άμεσα!")
    
    # Ξεκινάμε το αόρατο ραντάρ συγχρονισμού (Fragments)
    background_sync()
