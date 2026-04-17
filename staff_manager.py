import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import calendar
import io

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- Ρύθμιση σελίδας ---
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

# --- ΟΘΟΝΗ ΣΥΝΔΕΣΗΣ (AUTHENTICATION) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🔒 Staff Manager Pro</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Παρακαλώ εισάγετε τον κωδικό πρόσβασης για να συνεχίσετε.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            password = st.text_input("Κωδικός Πρόσβασης", type="password")
            submit = st.form_submit_button("Είσοδος", use_container_width=True)
            
            if submit:
                # Έλεγχος κωδικού (Από secrets ή προεπιλογή το admin123)
                correct_password = st.secrets.get("APP_PASSWORD", "admin123")
                if password == correct_password:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Λάθος κωδικός πρόσβασης. Δοκιμάστε ξανά.")
    
    # Σταματάει την εκτέλεση του υπόλοιπου κώδικα αν δεν γίνει σύνδεση
    st.stop()


# Check if secrets exist safely
try:
    HAS_SECRETS = "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets
except Exception:
    HAS_SECRETS = False

# --- SUPABASE CONNECTION & HELPERS ---
@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED:
        return None
    if HAS_SECRETS:
        try:
            return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        except Exception:
            pass
    return None

supabase = init_supabase()

@st.cache_data(ttl=15)
def fetch_all_data_from_db():
    """
    Αντλεί όλα τα δεδομένα από το Supabase. 
    Διατηρείται στη μνήμη (cache) για 15 δευτερόλεπτα για να μην καθυστερεί η εφαρμογή στα απανωτά κλικ, 
    αλλά να φέρνει συχνά τις αλλαγές των άλλων χρηστών.
    """
    if not supabase:
        return None
    try:
        emps = supabase.table("employees").select("*").execute().data
        projs = supabase.table("projects").select("*").execute().data
        
        assigns = supabase.table("assignments").select("*").execute().data
        for a in assigns:
            if isinstance(a.get('date'), str):
                a['date'] = datetime.strptime(a['date'], "%Y-%m-%d").date()
                
        leaves = supabase.table("leaves").select("*").execute().data
        for l in leaves:
            if isinstance(l.get('startDate'), str):
                l['startDate'] = datetime.strptime(l['startDate'], "%Y-%m-%d").date()
            if isinstance(l.get('endDate'), str):
                l['endDate'] = datetime.strptime(l['endDate'], "%Y-%m-%d").date()
                
        patterns = supabase.table("recurring_patterns").select("*").execute().data
        for p in patterns:
            if isinstance(p.get('startDate'), str):
                p['startDate'] = datetime.strptime(p['startDate'], "%Y-%m-%d").date()
                
        return {
            "employees": emps,
            "projects": projs,
            "assignments": assigns,
            "leaves": leaves,
            "recurring_patterns": patterns
        }
    except Exception as e:
        print(f"Σφάλμα ανάγνωσης από Supabase: {e}")
        return None

def serialize_dates(data):
    """Μετατρέπει τα ημερολογιακά objects σε string για να μπουν σωστά στη βάση (Supabase/JSON)."""
    if isinstance(data, list):
        return [serialize_dates(item) for item in data]
    elif isinstance(data, dict):
        return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in data.items()}
    return data

def db_insert(table, data):
    """Αποθηκεύει μία εγγραφή ή λίστα εγγραφών στη βάση."""
    if supabase:
        try:
            supabase.table(table).insert(serialize_dates(data)).execute()
            fetch_all_data_from_db.clear() # Άδειασμα της cache για άμεση ανανέωση δεδομένων!
        except Exception as e:
            st.error(f"Σφάλμα αποθήκευσης στη βάση (Table: {table}): {e}")

def db_delete(table, column, value):
    """Διαγράφει εγγραφές με βάση μια συνθήκη."""
    if supabase:
        try:
            supabase.table(table).delete().eq(column, value).execute()
            fetch_all_data_from_db.clear()
        except Exception as e:
            st.error(f"Σφάλμα διαγραφής στη βάση: {e}")

def db_delete_in(table, column, values):
    """Διαγράφει πολλές εγγραφές με βάση λίστα τιμών (IN)."""
    if supabase and values:
        try:
            supabase.table(table).delete().in_(column, values).execute()
            fetch_all_data_from_db.clear()
        except Exception as e:
            st.error(f"Σφάλμα μαζικής διαγραφής: {e}")

def db_update(table, id_val, new_data):
    """Ενημερώνει μια εγγραφή με βάση το ID της."""
    if supabase:
        try:
            supabase.table(table).update(serialize_dates(new_data)).eq('id', id_val).execute()
            fetch_all_data_from_db.clear()
        except Exception as e:
            st.error(f"Σφάλμα ενημέρωσης στη βάση: {e}")

# --- 10 Βασικά Χρώματα ---
BASIC_COLORS = {
    "Μπλε": "#4a86e8",
    "Κόκκινο": "#e00000",
    "Πράσινο": "#6aa84f",
    "Κίτρινο": "#f1c232",
    "Μωβ": "#8e7cc3",
    "Πορτοκαλί": "#e69138",
    "Γαλάζιο": "#00ffff",
    "Ροζ": "#c90076",
    "Σκούρο Πράσινο": "#38761d",
    "Γκρι": "#999999"
}

# --- Συνεχής Φόρτωση Δεδομένων (Real-time Sync Logic) ---
db_data = fetch_all_data_from_db()

if db_data is not None:
    st.session_state.employees = db_data["employees"]
    st.session_state.projects = db_data["projects"]
    st.session_state.assignments = db_data["assignments"]
    st.session_state.leaves = db_data["leaves"]
    st.session_state.recurring_patterns = db_data["recurring_patterns"]
    st.session_state.is_cloud = True
else:
    # Αν ΔΕΝ βρέθηκε Supabase ή υπήρξε σφάλμα, φορτώνουμε τα MOCK δεδομένα (Local mode)
    if 'local_data_loaded' not in st.session_state:
        st.session_state.local_data_loaded = True
        st.session_state.is_cloud = False
        st.session_state.employees = [
            {'id': '1', 'name': 'Γιάννης Παπαδόπουλος', 'position': 'ΕΡΓΑΤΗΣ', 'id_number': 'ΑΙ123456', 'phone': '6912345678', 'status': 'Ενεργός'},
            {'id': '2', 'name': 'Μαρία Παππά', 'position': 'ΕΠΟΠΤΗΣ', 'id_number': 'ΑΚ654321', 'phone': '6987654321', 'status': 'Ενεργός'},
            {'id': '3', 'name': 'Νίκος Νικολάου', 'position': 'ΟΔΗΓΟΣ', 'id_number': 'ΑΜ987654', 'phone': '6900000000', 'status': 'Ενεργός'},
        ]
        st.session_state.projects = [
            {'id': 'p1', 'name': 'Ανακαίνιση Γραφείων', 'color': '#4a86e8'},
            {'id': 'p2', 'name': 'Συντήρηση Δικτύου', 'color': '#e69138'},
        ]
        st.session_state.assignments = []
        st.session_state.recurring_patterns = []
        st.session_state.leaves = []

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

# --- Helpers ---
def get_employee_name(emp_id):
    for emp in st.session_state.employees:
        if emp['id'] == emp_id:
            return emp['name']
    return "Άγνωστος"

def get_project_info(proj_id):
    for proj in st.session_state.projects:
        if proj['id'] == proj_id:
            return proj
    return None

def is_on_leave(emp_id, check_date):
    for l in st.session_state.leaves:
        if l['employeeId'] == emp_id and l['startDate'] <= check_date <= l['endDate']:
            return True
    return False

def has_time_conflict(emp_id, check_date, t_start, t_end, exclude_ids=None):
    if exclude_ids is None:
        exclude_ids = []
        
    new_start = datetime.strptime(t_start, "%H:%M").time()
    new_end = datetime.strptime(t_end, "%H:%M").time()
    
    for a in st.session_state.assignments:
        if a['employeeId'] == emp_id and a['date'] == check_date and a['id'] not in exclude_ids:
            a_start = datetime.strptime(a['startTime'], "%H:%M").time()
            a_end = datetime.strptime(a['endTime'], "%H:%M").time()
            
            # Έλεγχος αν οι ώρες τέμνονται (overlap)
            if new_start < a_end and new_end > a_start:
                return True
    return False

def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)

# --- Sidebar Navigation ---
st.sidebar.title("STAFF.PRO")
menu = st.sidebar.radio("Μενού", [
    "Ταμπλό Gantt", 
    "Διαχείριση Έργων", 
    "Ομάδα Προσωπικού", 
    "Άδειες",
    "Σύνολο Αδειών",
    "Επαναλαμβανόμενες Εργασίες",
    "Ώρες Εργασιών"
])

st.sidebar.write("---")
st.sidebar.subheader("Κατάσταση Συστήματος")

# Διαγνωστικός Έλεγχος & Έλεγχος Αποσύνδεσης
if st.session_state.get('is_cloud'):
    st.sidebar.success("✅ Cloud Sync (Ανανέωση 15s)")
    if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
        fetch_all_data_from_db.clear()
        st.rerun()
else:
    st.sidebar.error("❌ Εκτός Σύνδεσης (Τοπικά)")
    if not SUPABASE_INSTALLED:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Το Streamlit δεν διάβασε το requirements.txt. Κάνε Reboot την εφαρμογή.")
    elif not HAS_SECRETS:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY) στις ρυθμίσεις του Streamlit.")
    else:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Υπήρξε σφάλμα κατά τη σύνδεση ή τη φόρτωση από τη βάση. Ελέγξτε αν έχετε απενεργοποιήσει το RLS σε όλους τους πίνακες.")

st.sidebar.write("---")
if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()

# --- ΛΙΣΤΑ ΜΟΝΟ ΕΝΕΡΓΩΝ ΥΠΑΛΛΗΛΩΝ (Για τις φόρμες επιλογής) ---
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- VIEW: DASHBOARD (GANTT) ---
if menu == "Ταμπλό Gantt":
    st.title("📅 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")
    
    # Μενού πλοήγησης εβδομάδων
    col_nav1, col_date, col_nav2, col_space, col_pres = st.columns([1, 2, 1, 0.5, 3])
    with col_nav1:
        st.write("")
        st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    with col_nav2:
        st.write("")
        st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox("🖥️ Λειτουργία Πλήρους Προβολής")
    
    data = []
    export_data = [] # Λίστα για τα δεδομένα που θα εξαχθούν στο Excel
    color_map = {}
    y_category_order = []
    tickvals = []
    ticktext = []
    
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    
    # Διατρέχουμε και τις 7 μέρες της εβδομάδας
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        # Υπολογισμός αδειών για την τρέχουσα μέρα
        leaves_today = [get_employee_name(l['employeeId']) for l in st.session_state.leaves if l['startDate'] <= curr_date <= l['endDate']]
        leaves_str = ", ".join(leaves_today) if leaves_today else "Καμία"
        
        # Η βασική ετικέτα του άξονα Y για αυτή τη μέρα
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        day_assignments = [a for a in st.session_state.assignments if a['date'] == curr_date]
        
        # Αν η μέρα δεν έχει καθόλου εργασίες, δημιουργούμε μια διάφανη καταχώρηση
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            y_category_order.append(row_id)
            tickvals.append(row_id)
            ticktext.append(base_y_label)
            
            data.append({
                'Y_Axis': row_id,
                'Έργο': 'Κενό',
                'Έναρξη': datetime(1970, 1, 1, 8, 0),
                'Λήξη': datetime(1970, 1, 1, 8, 0),
                'Προσωπικό': '',
                'Παρατηρήσεις': '',
                'Ετικέτα': '',
                'LegendGroup': 'Κενό',
                'ColorHex': 'rgba(0,0,0,0)'
            })
            color_map['Κενό'] = 'rgba(0,0,0,0)'
            continue
            
        # Ομαδοποίηση εργασιών της τρέχουσας μέρας
        groups = {}
        for a in day_assignments:
            proj = get_project_info(a['projectId'])
            c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
            c_name = a.get('colorName', "Προεπιλογή")
            notes = a.get('notes', '')
            
            key = f"{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}"
            if key not in groups:
                legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                groups[key] = {
                    'Project': proj['name'] if proj else "Άγνωστο",
                    'StartTime': a['startTime'],
                    'EndTime': a['endTime'],
                    'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['startTime'], "%H:%M").time()),
                    'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['endTime'], "%H:%M").time()),
                    'Employees': [],
                    'ColorHex': c_hex,
                    'Notes': notes,
                    'LegendGroup': legend_val
                }
            
            # Μορφοποίηση ονόματος: Επώνυμο + Αρχικό Ονόματος (π.χ. ΠΑΠΑΔΟΠΟΥΛΟΣ Γ.)
            full_name = get_employee_name(a['employeeId'])
            name_parts = full_name.split()
            if len(name_parts) > 1:
                first_name_initial = name_parts[0][0] + "."
                last_name = name_parts[-1]
                formatted_name = f"{last_name} {first_name_initial}"
            else:
                formatted_name = full_name
                
            groups[key]['Employees'].append(formatted_name)

        # Αλγόριθμος πακεταρίσματος για αποφυγή επικαλύψεων (Lanes)
        sorted_groups = sorted(groups.values(), key=lambda x: x['Start'])
        lanes = [] 
        group_row_mapping = []
        
        for g in sorted_groups:
            placed = False
            for lane_idx, lane_end in enumerate(lanes):
                if g['Start'] >= lane_end:
                    row_idx = lane_idx
                    lanes[lane_idx] = g['End']
                    placed = True
                    break
            
            if not placed:
                lanes.append(g['End'])
                row_idx = len(lanes) - 1
            
            group_row_mapping.append((g, row_idx))

        num_lanes = len(lanes)
        middle_lane = num_lanes // 2  # Υπολογισμός της μεσαίας σειράς για κεντράρισμα του κειμένου
        
        day_row_ids = []
        for row_idx in range(num_lanes):
            row_id = f"day_{i}_row_{row_idx}"
            y_category_order.append(row_id)
            tickvals.append(row_id)
            
            # Το όνομα της μέρας θα εμφανιστεί ΜΟΝΟ στη μεσαία σειρά
            if row_idx == middle_lane:
                ticktext.append(base_y_label)
            else:
                ticktext.append("")
                
            day_row_ids.append(row_id)

        # Δημιουργία τελικών δεδομένων προς σχεδίαση
        for g, row_idx in group_row_mapping:
            row_id = day_row_ids[row_idx]
            
            emps_str = ", ".join(g['Employees']).upper()
            proj_name = g['Project'].upper()
            times_str = f"{g['StartTime']}-{g['EndTime']}"
            
            label_text = f"{times_str} {proj_name} // {emps_str}"
            if g['Notes']:
                label_text += f" ({g['Notes'].upper()})"
                
            data.append({
                'Y_Axis': row_id,
                'Έργο': g['Project'],
                'Έναρξη': g['Start'],
                'Λήξη': g['End'],
                'Προσωπικό': ", ".join(g['Employees']),
                'Παρατηρήσεις': g['Notes'],
                'Ετικέτα': label_text,
                'LegendGroup': g['LegendGroup'],
                'ColorHex': g['ColorHex']
            })
            
            # Προσθήκη δεδομένων για το αρχείο Excel
            export_data.append({
                'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                'Ημέρα': day_names_gr[i],
                'Έργο': g['Project'],
                'Προσωπικό': ", ".join(g['Employees']),
                'Ώρα Έναρξης': g['StartTime'],
                'Ώρα Λήξης': g['EndTime'],
                'Παρατηρήσεις': g['Notes']
            })
            
            color_map[g['LegendGroup']] = g['ColorHex']
        
    df = pd.DataFrame(data)
    
    # Σταθερά όρια άξονα Χ (από 07:00 το πρωί έως 23:00 το βράδυ)
    day_start = datetime(1970, 1, 1, 7, 0)
    day_end = datetime(1970, 1, 1, 23, 0)
    
    # Σχεδιασμός Γραφήματος
    fig = px.timeline(
        df, 
        x_start="Έναρξη", 
        x_end="Λήξη", 
        y="Y_Axis", 
        color="LegendGroup",
        color_discrete_map=color_map,
        hover_data=["Έργο", "Προσωπικό", "Παρατηρήσεις"],
        text="Ετικέτα"
    )
    
    # Αντιστροφή της λίστας για να φαίνεται η Δευτέρα πάνω-πάνω
    fig.update_yaxes(
        categoryorder='array', 
        categoryarray=y_category_order[::-1],
        tickmode='array',
        tickvals=tickvals,
        ticktext=ticktext,
        showgrid=False # Κρύβουμε τις εσωτερικές γραμμές για να φαίνονται ενωμένα τα κελιά
    )
    
    # --- EXCEL STYLING & BORDERS ---
    fig.update_traces(
        textposition='inside', 
        insidetextanchor='middle',
        textfont=dict(color='black', size=11 if not presentation_mode else 12, family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1))
    )
    
    dynamic_height = max(500, len(y_category_order) * 60 + 100)
    
    fig.update_layout(
        showlegend=False, 
        plot_bgcolor='#dbece8', 
        paper_bgcolor='#ffffff',
        height=dynamic_height,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(
            side='top', 
            tickmode='linear',
            tick0=day_start,
            dtick=1800000, # Κάθε 30 λεπτά
            tickformat="%H:%M",
            showgrid=True,
            gridcolor='#a8c8c0',
            gridwidth=1,
            range=[day_start, day_end],
            title="",
            tickfont=dict(size=11, color="black", family="Arial"),
            fixedrange=False,
            rangeslider=dict(visible=True, thickness=0.04, bgcolor="#e2e8f0") # Εμφάνιση μπάρας κύλισης
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=12, color="black"),
            fixedrange=False
        ),
        dragmode="pan"
    )
    
    # --- ΠΡΟΣΘΗΚΗ ΠΑΧΙΩΝ ΔΙΑΧΩΡΙΣΤΙΚΩΝ ΓΡΑΜΜΩΝ ΑΝΑΜΕΣΑ ΣΤΙΣ ΗΜΕΡΕΣ ---
    for idx in range(len(y_category_order) - 1):
        row_below = y_category_order[::-1][idx]
        row_above = y_category_order[::-1][idx+1]
        
        day_below = row_below.split('_')[1]
        day_above = row_above.split('_')[1]
        
        if day_below != day_above:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#1f2937", width=2))
            
    fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=-0.5, y1=-0.5, yref="y", line=dict(color="#1f2937", width=2))
    fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=len(y_category_order)-0.5, y1=len(y_category_order)-0.5, yref="y", line=dict(color="#1f2937", width=2))

    # --- ΕΠΙΣΗΜΑΝΣΗ ΤΗΣ ΣΗΜΕΡΙΝΗΣ ΗΜΕΡΑΣ ---
    today_date = date.today()
    today_day_index = (today_date - start_of_week).days
    
    if 0 <= today_day_index < 7:
        today_indices = [idx for idx, val in enumerate(y_category_order[::-1]) if val.startswith(f"day_{today_day_index}_")]
        if today_indices:
            min_idx = min(today_indices)
            max_idx = max(today_indices)
            fig.add_hrect(
                y0=min_idx - 0.5, 
                y1=max_idx + 0.5, 
                fillcolor="#b2d8ce", 
                opacity=1, 
                layer="below", 
                line_width=0
            )

    st.markdown(f"### 🗓️ Εβδομάδα: {start_of_week.strftime('%d/%m/%Y')} έως {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}")
    st.plotly_chart(fig, use_container_width=True)
    
    # --- ΕΞΑΓΩΓΗ ΣΕ EXCEL ΚΑΙ ΣΥΜΒΟΥΛΕΣ ---
    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint:
            st.caption("💡 *Συμβουλές Προβολής:* **1)** Σύρετε το διάγραμμα με το ποντίκι ή την **κάτω μπάρα κύλισης**. **2)** Χρησιμοποιήστε το ροδάκι για Zoom. **3)** Διπλό κλικ για επαναφορά.")
        with col_btn:
            df_export = pd.DataFrame(export_data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            
            st.download_button(
                label="📥 Εξαγωγή Προγράμματος (Excel)",
                data=buffer.getvalue(),
                file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.caption("💡 *Συμβουλές Προβολής:* **1)** Σύρετε το διάγραμμα με το ποντίκι ή την **κάτω μπάρα κύλισης**. **2)** Χρησιμοποιήστε το ροδάκι για Zoom. **3)** Διπλό κλικ για επαναφορά.")

    if not presentation_mode:
        st.divider()

        col_add, col_edit = st.columns(2)

        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            with st.form("quick_add", clear_on_submit=True):
                add_date = st.date_input("Ημερομηνία", value=selected_date)
                
                proj_choice = st.selectbox("Έργο", options=[p['id'] for p in st.session_state.projects], 
                                         format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                
                # Φιλτράρισμα: Μόνο ενεργοί υπάλληλοι
                emp_choices = st.multiselect("Προσωπικό (Μόνο Ενεργοί)", options=active_employee_ids,
                                           format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
                
                c_color, c_notes = st.columns(2)
                with c_color:
                    color_choice = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()))
                with c_notes:
                    add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key="add_notes")
                
                c_start, c_end = st.columns(2)
                with c_start:
                    t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key="add_s")
                with c_end:
                    t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key="add_e")
                    
                if st.form_submit_button("Καταχώρηση"):
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")
                    
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    elif not emp_choices:
                        st.error("Επιλέξτε τουλάχιστον έναν εργαζόμενο.")
                    else:
                        errors = []
                        for eid in emp_choices:
                            emp_name = get_employee_name(eid)
                            if is_on_leave(eid, add_date):
                                errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {add_date.strftime('%d/%m')}.")
                            elif has_time_conflict(eid, add_date, str_start, str_end):
                                errors.append(f"Ο/Η {emp_name} έχει ήδη εργασία που συμπίπτει στις {add_date.strftime('%d/%m')}.")
                        
                        if errors:
                            for err in errors:
                                st.error(err)
                        else:
                            for eid in emp_choices:
                                new_assign = {
                                    'id': str(uuid.uuid4()),
                                    'employeeId': eid,
                                    'projectId': proj_choice,
                                    'date': add_date,
                                    'startTime': str_start,
                                    'endTime': str_end,
                                    'colorName': color_choice,
                                    'colorHex': BASIC_COLORS[color_choice],
                                    'notes': add_notes,
                                    'recurring_id': None
                                }
                                st.session_state.assignments.append(new_assign)
                                db_insert("assignments", new_assign)
                            
                            st.success("Η ανάθεση ολοκληρώθηκε!")
                            st.rerun()

        with col_edit:
            st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
            
            weekly_groups = {}
            weekly_assignments = [a for a in st.session_state.assignments if start_of_week <= a['date'] <= start_of_week + timedelta(days=6)]
            
            for a in weekly_assignments:
                proj = get_project_info(a['projectId'])
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', '')
                
                key = f"{a['date']}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}"
                if key not in weekly_groups:
                    weekly_groups[key] = {
                        'Date': a['date'],
                        'ProjectId': a['projectId'],
                        'Project': proj['name'] if proj else "Άγνωστο",
                        'StartTime': a['startTime'],
                        'EndTime': a['endTime'],
                        'EmployeeIds': [],
                        'AssignmentIds': [],
                        'ColorName': c_name,
                        'Notes': notes
                    }
                weekly_groups[key]['EmployeeIds'].append(a['employeeId'])
                weekly_groups[key]['AssignmentIds'].append(a['id'])

            if not weekly_groups:
                st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
            else:
                group_keys = list(weekly_groups.keys())
                group_keys.sort(key=lambda k: (weekly_groups[k]['Date'], weekly_groups[k]['StartTime']))
                
                selected_key = st.selectbox(
                    "Επιλέξτε Μπάρα (Ημέρα & Έργο)", 
                    options=[""] + group_keys,
                    format_func=lambda x: "Επιλέξτε..." if x == "" else f"{weekly_groups[x]['Date'].strftime('%d/%m')} - {weekly_groups[x]['Project']} ({weekly_groups[x]['StartTime']}-{weekly_groups[x]['EndTime']})"
                )
                
                if selected_key != "":
                    target_group = weekly_groups[selected_key]
                    
                    with st.form("quick_edit"):
                        edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group['Date'])
                        
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0
                        
                        edit_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, 
                                                 index=default_proj_idx,
                                                 format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                        
                        # Στην επεξεργασία: Δείχνουμε τους ενεργούς + όσους είναι ήδη στην εργασία (ακόμα κι αν πλέον είναι ανενεργοί)
                        edit_options = list(set(active_employee_ids + target_group['EmployeeIds']))
                        edit_emps = st.multiselect("Αλλαγή Προσωπικού", options=edit_options,
                                                   default=target_group['EmployeeIds'],
                                                   format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                        
                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            default_color_idx = list(BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in BASIC_COLORS else 0
                            edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=default_color_idx)
                        with e_notes_col:
                            edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=target_group['Notes'], key="edit_notes")

                        e_start, e_end = st.columns(2)
                        with e_start:
                            new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(target_group['StartTime'], "%H:%M").time(), key="edit_s")
                        with e_end:
                            new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(target_group['EndTime'], "%H:%M").time(), key="edit_e")
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            save_edit = st.form_submit_button("💾 Αποθήκευση")
                        with col_btn2:
                            del_edit = st.form_submit_button("🗑️ Διαγραφή Μπάρας")
                            
                        if del_edit:
                            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                            db_delete_in('assignments', 'id', target_group['AssignmentIds'])
                            st.rerun()
                            
                        if save_edit:
                            str_start = new_t_start.strftime("%H:%M")
                            str_end = new_t_end.strftime("%H:%M")
                            
                            if str_start >= str_end:
                                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                            elif not edit_emps:
                                st.error("Επιλέξτε τουλάχιστον έναν εργαζόμενο.")
                            else:
                                errors = []
                                for eid in edit_emps:
                                    emp_name = get_employee_name(eid)
                                    if is_on_leave(eid, edit_date):
                                        errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {edit_date.strftime('%d/%m')}.")
                                    elif has_time_conflict(eid, edit_date, str_start, str_end, exclude_ids=target_group['AssignmentIds']):
                                        errors.append(f"Ο/Η {emp_name} έχει ήδη εργασία που συμπίπτει.")
                                        
                                if errors:
                                    for err in errors:
                                        st.error(err)
                                else:
                                    st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                    db_delete_in('assignments', 'id', target_group['AssignmentIds'])
                                    
                                    for eid in edit_emps:
                                        new_a = {
                                            'id': str(uuid.uuid4()),
                                            'employeeId': eid,
                                            'projectId': edit_proj,
                                            'date': edit_date,
                                            'startTime': str_start,
                                            'endTime': str_end,
                                            'colorName': edit_color,
                                            'colorHex': BASIC_COLORS[edit_color],
                                            'notes': edit_notes,
                                            'recurring_id': None 
                                        }
                                        st.session_state.assignments.append(new_a)
                                        db_insert('assignments', new_a)
                                    st.rerun()

# --- VIEW: RECURRING TASKS ---
elif menu == "Επαναλαμβανόμενες Εργασίες":
    st.title("🔄 Επαναλαμβανόμενες Εργασίες")
    st.write("Προσθέστε ή επεξεργαστείτε εργασίες που επαναλαμβάνονται «για πάντα» (προγραμματίζονται αυτόματα για τα επόμενα 3 χρόνια).")
    
    tab_new, tab_edit = st.tabs(["➕ Νέα Καταχώρηση", "✏️ Διαχείριση/Επεξεργασία Υπαρχουσών"])
    
    # --- ΚΑΡΤΕΛΑ 1: ΝΕΑ ΚΑΤΑΧΩΡΗΣΗ ---
    with tab_new:
        r_col1, r_col2 = st.columns(2)
        
        with r_col1:
            r_proj = st.selectbox("Έργο", options=[p['id'] for p in st.session_state.projects], 
                                     format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"), key="new_r_proj")
            
            # Φιλτράρισμα: Μόνο ενεργοί υπάλληλοι
            r_emps = st.multiselect("Προσωπικό (Μόνο Ενεργοί)", options=active_employee_ids,
                                       format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key="new_r_emps")
            
            c_r_color, c_r_notes = st.columns(2)
            with c_r_color:
                r_color = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key="new_r_color")
            with c_r_notes:
                r_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key="new_r_notes")
            
            r_type = st.selectbox("Συχνότητα Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"], key="new_r_type")
            
            selected_weekdays = []
            if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                st.caption("Επιλέξτε Μέρες (τικάρετε τα κουτάκια):")
                day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                cols = st.columns(4)
                for i, d_name in enumerate(day_names):
                    if cols[i % 4].checkbox(d_name, value=(i==0), key=f"new_chk_{i}"):
                        selected_weekdays.append(d_name)
        
        with r_col2:
            r_start_date = st.date_input("Από Ημερομηνία", date.today(), key="new_r_start_date")
            r_start_time = st.time_input("Έναρξη Ώρας", value=datetime.strptime("09:00", "%H:%M").time(), key="new_r_start_time")
            r_end_time = st.time_input("Λήξη Ώρας", value=datetime.strptime("17:00", "%H:%M").time(), key="new_r_end_time")
            
            st.info("💡 Η εργασία θα επαναλαμβάνεται συνεχώς.")
        
        st.write("") 
        if st.button("Καταχώρηση Επαναλαμβανόμενης Εργασίας", type="primary", key="btn_new_r"):
            str_start = r_start_time.strftime("%H:%M")
            str_end = r_end_time.strftime("%H:%M")
            
            if str_start >= str_end:
                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
            elif not r_emps:
                st.error("Επιλέξτε τουλάχιστον έναν εργαζόμενο.")
            elif r_type == "Επιλεγμένες Μέρες Εβδομάδας" and not selected_weekdays:
                st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας τικάροντας το αντίστοιχο κουτάκι.")
            else:
                pattern_id = str(uuid.uuid4())
                r_end_date = r_start_date + timedelta(days=365 * 3)
                
                dates_to_assign = []
                curr_date = r_start_date
                day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
                
                new_assignments_batch = []
                
                with st.spinner('Υπολογισμός και καταχώρηση βαρδιών...'):
                    while curr_date <= r_end_date:
                        if r_type == "Εβδομαδιαία":
                            dates_to_assign.append(curr_date)
                            curr_date += timedelta(days=7)
                        elif r_type == "Μηνιαία":
                            dates_to_assign.append(curr_date)
                            month = curr_date.month
                            year = curr_date.year
                            if month == 12:
                                month = 1
                                year += 1
                            else:
                                month += 1
                            try:
                                curr_date = curr_date.replace(year=year, month=month)
                            except ValueError:
                                last_day = calendar.monthrange(year, month)[1]
                                curr_date = curr_date.replace(year=year, month=month, day=last_day)
                        elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                            if curr_date.weekday() in selected_weekday_ints:
                                dates_to_assign.append(curr_date)
                            curr_date += timedelta(days=1)
                    
                    success_count = 0
                    conflict_count = 0
                    conflict_details = []
                    
                    for d in dates_to_assign:
                        for eid in r_emps:
                            emp_name = get_employee_name(eid)
                            if is_on_leave(eid, d):
                                conflict_count += 1
                                conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Άδεια)")
                            elif has_time_conflict(eid, d, str_start, str_end):
                                conflict_count += 1
                                conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Επικάλυψη)")
                            else:
                                new_assign = {
                                    'id': str(uuid.uuid4()),
                                    'recurring_id': pattern_id,
                                    'employeeId': eid,
                                    'projectId': r_proj,
                                    'date': d,
                                    'startTime': str_start,
                                    'endTime': str_end,
                                    'colorName': r_color,
                                    'colorHex': BASIC_COLORS[r_color],
                                    'notes': r_notes
                                }
                                new_assignments_batch.append(new_assign)
                                success_count += 1
                    
                    new_pattern = {
                        'id': pattern_id,
                        'projectId': r_proj,
                        'employeeIds': r_emps,
                        'colorName': r_color,
                        'notes': r_notes,
                        'type': r_type,
                        'weekdays': selected_weekdays,
                        'startDate': r_start_date,
                        'startTime': str_start,
                        'endTime': str_end
                    }
                    
                    # Update Memory & DB
                    st.session_state.recurring_patterns.append(new_pattern)
                    db_insert('recurring_patterns', new_pattern)
                    
                    if new_assignments_batch:
                        st.session_state.assignments.extend(new_assignments_batch)
                        # Χρησιμοποιούμε μαζική εισαγωγή για ταχύτητα
                        db_insert('assignments', new_assignments_batch)
                    
                if success_count > 0:
                    st.success(f"Επιτυχής δημιουργία {success_count} βαρδιών για τα επόμενα 3 χρόνια!")
                if conflict_count > 0:
                    st.warning(f"Παραλείφθηκαν {conflict_count} αναθέσεις λόγω συγκρούσεων.")
                    with st.expander("Δείτε τις συγκρούσεις"):
                        for c in conflict_details:
                            st.write(f"⚠️ {c}")

    # --- ΚΑΡΤΕΛΑ 2: ΔΙΑΧΕΙΡΙΣΗ / ΕΠΕΞΕΡΓΑΣΙΑ ---
    with tab_edit:
        if not st.session_state.recurring_patterns:
            st.info("Δεν υπάρχουν ενεργές επαναλαμβανόμενες εργασίες.")
        else:
            pattern_options = {}
            for p in st.session_state.recurring_patterns:
                p_info = get_project_info(p['projectId'])
                p_name = p_info['name'] if p_info else 'Άγνωστο Έργο'
                pattern_options[p['id']] = f"{p_name} | {p['type']} | Από: {p['startDate'].strftime('%d/%m/%Y')} ({p['startTime']}-{p['endTime']})"
            
            selected_pattern_id = st.selectbox("Επιλέξτε Σειρά Εργασιών", options=list(pattern_options.keys()), format_func=lambda x: pattern_options[x])
            
            if selected_pattern_id:
                pat = next(p for p in st.session_state.recurring_patterns if p['id'] == selected_pattern_id)
                
                with st.form("edit_recurring_form"):
                    st.warning("⚠️ Προσοχή: Η αποθήκευση αλλαγών θα επαναδημιουργήσει **ΟΛΕΣ** τις βάρδιες αυτής της σειράς. Τυχόν μεμονωμένες αλλαγές που κάνατε στο Ταμπλό θα χαθούν.")
                    
                    e_col1, e_col2 = st.columns(2)
                    with e_col1:
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(pat['projectId']) if pat['projectId'] in proj_ids else 0
                        e_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, 
                                                index=default_proj_idx,
                                                format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                        
                        edit_options_r = list(set(active_employee_ids + pat['employeeIds']))
                        e_emps = st.multiselect("Αλλαγή Προσωπικού", options=edit_options_r,
                                                  default=pat['employeeIds'],
                                                  format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                        
                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            e_color_idx = list(BASIC_COLORS.keys()).index(pat['colorName']) if pat['colorName'] in BASIC_COLORS else 0
                            e_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=e_color_idx)
                        with e_notes_col:
                            e_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=pat.get('notes', ''), key="edit_r_notes")

                    with e_col2:
                        e_start_date = st.date_input("Αλλαγή Ημερομηνίας Έναρξης", pat['startDate'])
                        e_start_time = st.time_input("Αλλαγή Ώρας Έναρξης", value=datetime.strptime(pat['startTime'], "%H:%M").time())
                        e_end_time = st.time_input("Αλλαγή Ώρας Λήξης", value=datetime.strptime(pat['endTime'], "%H:%M").time())

                    # Αν ήταν μέρες εβδομάδας, επιτρέπουμε αλλαγή ημερών
                    e_selected_weekdays = pat['weekdays']
                    e_type = pat['type']
                    if e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                        st.caption("Αλλαγή Επιλεγμένων Ημερών:")
                        day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                        cols = st.columns(4)
                        new_selected = []
                        for i, d_name in enumerate(day_names):
                            if cols[i % 4].checkbox(d_name, value=(d_name in pat['weekdays']), key=f"edit_chk_{i}"):
                                new_selected.append(d_name)
                        e_selected_weekdays = new_selected
                        
                    st.write("")
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        save_rec = st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary")
                    with col_b2:
                        del_rec = st.form_submit_button("🗑️ Διαγραφή ΟΛΗΣ της σειράς")
                        
                    if del_rec:
                        # Διαγράφουμε όλες τις βάρδιες και το pattern
                        st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                        st.session_state.recurring_patterns = [p for p in st.session_state.recurring_patterns if p['id'] != selected_pattern_id]
                        db_delete('assignments', 'recurring_id', selected_pattern_id)
                        db_delete('recurring_patterns', 'id', selected_pattern_id)
                        st.rerun()
                        
                    if save_rec:
                        str_start = e_start_time.strftime("%H:%M")
                        str_end = e_end_time.strftime("%H:%M")
                        
                        if str_start >= str_end:
                            st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                        elif not e_emps:
                            st.error("Επιλέξτε τουλάχιστον έναν εργαζόμενο.")
                        elif e_type == "Επιλεγμένες Μέρες Εβδομάδας" and not e_selected_weekdays:
                            st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας.")
                        else:
                            # 1. Αφαιρούμε τις παλιές εγγραφές της σειράς
                            st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                            db_delete('assignments', 'recurring_id', selected_pattern_id)
                            
                            # 2. Παράγουμε τις νέες
                            r_end_date = e_start_date + timedelta(days=365 * 3)
                            dates_to_assign = []
                            curr_date = e_start_date
                            day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                            selected_weekday_ints = [day_map[d] for d in e_selected_weekdays] if e_selected_weekdays else []
                            
                            new_assignments_batch = []
                            
                            with st.spinner('Ενημέρωση και καταχώρηση βαρδιών...'):
                                while curr_date <= r_end_date:
                                    if e_type == "Εβδομαδιαία":
                                        dates_to_assign.append(curr_date)
                                        curr_date += timedelta(days=7)
                                    elif e_type == "Μηνιαία":
                                        dates_to_assign.append(curr_date)
                                        month = curr_date.month
                                        year = curr_date.year
                                        if month == 12:
                                            month = 1
                                            year += 1
                                        else:
                                            month += 1
                                        try:
                                            curr_date = curr_date.replace(year=year, month=month)
                                        except ValueError:
                                            last_day = calendar.monthrange(year, month)[1]
                                            curr_date = curr_date.replace(year=year, month=month, day=last_day)
                                    elif e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                        if curr_date.weekday() in selected_weekday_ints:
                                            dates_to_assign.append(curr_date)
                                        curr_date += timedelta(days=1)
                                
                                for d in dates_to_assign:
                                    for eid in e_emps:
                                        if not is_on_leave(eid, d) and not has_time_conflict(eid, d, str_start, str_end):
                                            new_assign = {
                                                'id': str(uuid.uuid4()),
                                                'recurring_id': selected_pattern_id,
                                                'employeeId': eid,
                                                'projectId': e_proj,
                                                'date': d,
                                                'startTime': str_start,
                                                'endTime': str_end,
                                                'colorName': e_color,
                                                'colorHex': BASIC_COLORS[e_color],
                                                'notes': e_notes
                                            }
                                            new_assignments_batch.append(new_assign)
                                
                                # 3. Ενημερώνουμε τα δεδομένα του Pattern
                                pat['projectId'] = e_proj
                                pat['employeeIds'] = e_emps
                                pat['colorName'] = e_color
                                pat['notes'] = e_notes
                                pat['weekdays'] = e_selected_weekdays
                                pat['startDate'] = e_start_date
                                pat['startTime'] = str_start
                                pat['endTime'] = str_end
                                
                                db_update('recurring_patterns', selected_pattern_id, pat)
                                
                                if new_assignments_batch:
                                    st.session_state.assignments.extend(new_assignments_batch)
                                    db_insert('assignments', new_assignments_batch)
                                
                            st.rerun()

# --- VIEW: PROJECTS ---
elif menu == "Διαχείριση Έργων":
    st.title("🏗️ Έργα")
    with st.expander("Νέο Έργο"):
        p_name = st.text_input("Όνομα Έργου")
        p_color = st.color_picker("Χρώμα (Προεπιλογή)", "#4a86e8")
        if st.button("Δημιουργία"):
            new_p = {'id': str(uuid.uuid4()), 'name': p_name, 'color': p_color}
            st.session_state.projects.append(new_p)
            db_insert('projects', new_p)
            st.rerun()
            
    for p in st.session_state.projects:
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{p['name']}**")
        if col2.button("Διαγραφή", key=p['id']):
            st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
            db_delete('projects', 'id', p['id'])
            st.rerun()

# --- VIEW: EMPLOYEES ---
elif menu == "Ομάδα Προσωπικού":
    st.title("👥 Προσωπικό")
    
    tab_list, tab_add, tab_edit = st.tabs(["📋 Λίστα Υπαλλήλων", "➕ Προσθήκη Υπαλλήλου", "✏️ Επεξεργασία"])
    
    with tab_add:
        with st.form("new_emp", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                e_name = st.text_input("Ονοματεπώνυμο")
                e_pos = st.selectbox("Θέση", ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"])
            with c2:
                e_id_num = st.text_input("Αριθμός Ταυτότητας")
                e_phone = st.text_input("Κινητό Τηλέφωνο")
            with c3:
                e_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"])
                
            if st.form_submit_button("Προσθήκη Υπαλλήλου", type="primary"):
                if not e_name.strip():
                    st.error("Το πεδίο 'Ονοματεπώνυμο' είναι υποχρεωτικό.")
                else:
                    is_duplicate = False
                    for emp in st.session_state.employees:
                        if emp['name'].strip().lower() == e_name.strip().lower():
                            st.error(f"Ο/Η υπάλληλος '{emp['name']}' υπάρχει ήδη στη λίστα.")
                            is_duplicate = True
                            break
                        if e_id_num.strip() and emp.get('id_number', '').strip().lower() == e_id_num.strip().lower():
                            st.error(f"Ο Αριθμός Ταυτότητας '{e_id_num}' ανήκει ήδη στον/στην '{emp['name']}'.")
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        new_e = {
                            'id': str(uuid.uuid4()), 
                            'name': e_name.strip(), 
                            'position': e_pos.strip(),
                            'id_number': e_id_num.strip(),
                            'phone': e_phone.strip(),
                            'status': e_status
                        }
                        st.session_state.employees.append(new_e)
                        db_insert('employees', new_e)
                        st.success(f"Ο/Η '{e_name.strip()}' προστέθηκε με επιτυχία!")
    
    with tab_edit:
        if not st.session_state.employees:
            st.info("Δεν υπάρχουν υπάλληλοι προς επεξεργασία.")
        else:
            emp_to_edit_id = st.selectbox("Επιλέξτε Υπάλληλο για Επεξεργασία", 
                                          options=[e['id'] for e in st.session_state.employees],
                                          format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
            
            emp_to_edit = next(e for e in st.session_state.employees if e['id'] == emp_to_edit_id)
            
            with st.form("edit_emp"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ed_name = st.text_input("Ονοματεπώνυμο", value=emp_to_edit['name'])
                    
                    pos_options = ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"]
                    current_pos = emp_to_edit.get('position', 'ΕΡΓΑΤΗΣ')
                    pos_index = pos_options.index(current_pos) if current_pos in pos_options else 0
                    ed_pos = st.selectbox("Θέση", pos_options, index=pos_index)
                    
                with c2:
                    ed_id_num = st.text_input("Αριθμός Ταυτότητας", value=emp_to_edit.get('id_number', ''))
                    ed_phone = st.text_input("Κινητό Τηλέφωνο", value=emp_to_edit.get('phone', ''))
                with c3:
                    current_status = emp_to_edit.get('status', 'Ενεργός')
                    ed_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"], index=0 if current_status == 'Ενεργός' else 1)
                    
                if st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary"):
                    if not ed_name.strip():
                        st.error("Το πεδίο 'Ονοματεπώνυμο' είναι υποχρεωτικό.")
                    else:
                        is_dup = False
                        for e in st.session_state.employees:
                            if e['id'] != emp_to_edit_id:
                                if e['name'].strip().lower() == ed_name.strip().lower():
                                    st.error("Υπάρχει ήδη άλλος υπάλληλος με αυτό το όνομα.")
                                    is_dup = True
                                    break
                                elif ed_id_num.strip() and e.get('id_number', '').strip().lower() == ed_id_num.strip().lower():
                                    st.error("Ο Αριθμός Ταυτότητας ανήκει ήδη σε άλλον υπάλληλο.")
                                    is_dup = True
                                    break
                        
                        if not is_dup:
                            emp_to_edit['name'] = ed_name.strip()
                            emp_to_edit['position'] = ed_pos.strip()
                            emp_to_edit['id_number'] = ed_id_num.strip()
                            emp_to_edit['phone'] = ed_phone.strip()
                            emp_to_edit['status'] = ed_status
                            
                            db_update('employees', emp_to_edit_id, emp_to_edit)
                            st.success("Οι αλλαγές αποθηκεύτηκαν!")
                            st.rerun()

    with tab_list:
        st.write("### Συνολική Λίστα Υπαλλήλων")
        
        # Επικεφαλίδες Στηλών
        hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2, 2, 2, 2, 1.5, 1])
        hc1.write("**Ονοματεπώνυμο**")
        hc2.write("**Θέση**")
        hc3.write("**Αρ. Ταυτότητας**")
        hc4.write("**Κινητό**")
        hc5.write("**Κατάσταση**")
        hc6.write("")
        st.divider()
        
        # Δεδομένα
        for e in st.session_state.employees:
            col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 2, 2, 1.5, 1])
            col1.write(e['name'])
            col2.write(f"*{e['position']}*")
            col3.write(e.get('id_number', '-'))
            col4.write(e.get('phone', '-'))
            
            status_val = e.get('status', 'Ενεργός')
            status_color = "#16a34a" if status_val == 'Ενεργός' else "#dc2626"
            col5.markdown(f"<span style='color:{status_color}; font-weight:bold;'>{status_val}</span>", unsafe_allow_html=True)
            
            if col6.button("❌", key=f"del_emp_{e['id']}"):
                st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] != e['id']]
                db_delete('employees', 'id', e['id'])
                st.rerun()

# --- VIEW: LEAVES ---
elif menu == "Άδειες":
    st.title("🏖️ Διαχείριση Αδειών")
    with st.form("new_leave"):
        l_emp = st.selectbox("Υπάλληλος (Μόνο Ενεργοί)", options=active_employee_ids, 
                             format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
        l_start = st.date_input("Από")
        l_end = st.date_input("Έως")
        
        if st.form_submit_button("Καταχώρηση Άδειας"):
            if not l_emp:
                st.error("Παρακαλώ επιλέξτε υπάλληλο.")
            elif l_start > l_end:
                st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
            else:
                # Έλεγχος αν ο υπάλληλος εργάζεται ήδη κάποια από τις μέρες της άδειας
                conflict_errors = []
                curr_date = l_start
                while curr_date <= l_end:
                    for a in st.session_state.assignments:
                        if a['employeeId'] == l_emp and a['date'] == curr_date:
                            proj = get_project_info(a['projectId'])
                            proj_name = proj['name'] if proj else "Άγνωστο Έργο"
                            emp_name = get_employee_name(l_emp)
                            conflict_errors.append(f"Ο/Η {emp_name} δεν μπορεί να πάρει άδεια στις {curr_date.strftime('%d/%m/%Y')} διότι εργάζεται στο έργο: {proj_name}.")
                            break # Αρκεί μία επικάλυψη για να μπλοκάρει τη μέρα
                    curr_date += timedelta(days=1)
                
                if conflict_errors:
                    for err in conflict_errors:
                        st.error(err)
                else:
                    new_l = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end}
                    st.session_state.leaves.append(new_l)
                    db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε με επιτυχία!")
                    st.rerun()
            
    if st.session_state.leaves:
        st.write("### Λίστα Αδειών")
        
        # Επικεφαλίδες Στηλών
        hc1, hc2, hc3, hc4 = st.columns([3, 2, 2, 1])
        hc1.write("**Υπάλληλος**")
        hc2.write("**Από**")
        hc3.write("**Έως**")
        hc4.write("")
        st.divider()
        
        # Δεδομένα
        for l in st.session_state.leaves:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.write(get_employee_name(l['employeeId']))
            col2.write(l['startDate'].strftime('%d/%m/%Y'))
            col3.write(l['endDate'].strftime('%d/%m/%Y'))
            if col4.button("❌", key=f"del_leave_{l['id']}"):
                st.session_state.leaves = [leave for leave in st.session_state.leaves if leave['id'] != l['id']]
                db_delete('leaves', 'id', l['id'])
                st.rerun()
    else:
        st.info("Δεν υπάρχουν καταχωρημένες άδειες.")

# --- VIEW: Σύνολο Αδειών ---
elif menu == "Σύνολο Αδειών":
    st.title("🏖️ Σύνολο Αδειών ανά Έτος")
    
    current_year = date.today().year
    years = list(range(2020, 2036))
    
    col1, col2 = st.columns([1, 3])
    with col1:
        selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
        
    st.divider()
    
    # Υπολογισμός ημερών άδειας
    leave_days = {emp['id']: 0 for emp in st.session_state.employees}
    
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)
    
    for l in st.session_state.leaves:
        start_d = l['startDate']
        end_d = l['endDate']
        
        # Υπολογισμός των ημερών της άδειας που πέφτουν ΜΕΣΑ στο επιλεγμένο έτος
        actual_start = max(start_d, year_start)
        actual_end = min(end_d, year_end)
        
        if actual_start <= actual_end:
            days = (actual_end - actual_start).days + 1
            if l['employeeId'] in leave_days:
                leave_days[l['employeeId']] += days
                
    # Προετοιμασία δεδομένων για τον πίνακα
    table_data = []
    for emp in st.session_state.employees:
        table_data.append({
            "Ονοματεπώνυμο": emp['name'],
            "Θέση": emp['position'],
            "Κατάσταση": emp.get('status', 'Ενεργός'),
            "Ημέρες Άδειας": leave_days[emp['id']]
        })
        
    df_leaves_summary = pd.DataFrame(table_data)
    
    st.write(f"### Συνολικές Ημέρες Άδειας για το έτος: {selected_year}")
    
    # Εμφάνιση του πίνακα
    st.dataframe(
        df_leaves_summary, 
        use_container_width=True,
        hide_index=True
    )

# --- VIEW: Ώρες Εργασιών ---
elif menu == "Ώρες Εργασιών":
    st.title("⏱️ Ώρες Εργασιών ανά Μήνα")
    
    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", 
              "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
    
    current_month_index = date.today().month - 1
    current_year = date.today().year
    
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        selected_month_name = st.selectbox("Επιλογή Μήνα", months, index=current_month_index)
        selected_month = months.index(selected_month_name) + 1
        
    with col2:
        # Παραγωγή λίστας ετών (π.χ. από το 2020 έως το 2035)
        years = list(range(2020, 2036))
        selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
        
    st.divider()
    
    # Υπολογισμός ωρών
    employee_hours = {emp['id']: 0.0 for emp in st.session_state.employees}
    
    for a in st.session_state.assignments:
        d = a['date']
        if d.month == selected_month and d.year == selected_year:
            # Υπολογισμός διαφοράς ωρών
            start = datetime.strptime(a['startTime'], "%H:%M")
            end = datetime.strptime(a['endTime'], "%H:%M")
            delta = end - start
            hours = delta.total_seconds() / 3600.0
            
            if a['employeeId'] in employee_hours:
                employee_hours[a['employeeId']] += hours
                
    # Προετοιμασία δεδομένων για τον πίνακα
    table_data = []
    for emp in st.session_state.employees:
        table_data.append({
            "Ονοματεπώνυμο": emp['name'],
            "Θέση": emp['position'],
            "Κατάσταση": emp.get('status', 'Ενεργός'),
            "Συνολικές Ώρες": round(employee_hours[emp['id']], 2)
        })
        
    df_hours = pd.DataFrame(table_data)
    
    st.write(f"### Σύνολο Ωρών για: {selected_month_name} {selected_year}")
    
    # Εμφάνιση του πίνακα
    st.dataframe(
        df_hours.style.format({"Συνολικές Ώρες": "{:.2f}"}), 
        use_container_width=True,
        hide_index=True
    )
