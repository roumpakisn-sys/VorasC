import streamlit as st
import streamlit.components.v1 as components
from datetime import date, timedelta
import json


def setup_shared_ui(show_menu=False, menu_options=None):
    import utils
    st.markdown("""
    <style>
    /* =========================================================
       STAFF.PRO sidebar HTML/CSS skin
       Αλλάζει μόνο εμφάνιση. Δεν αλλάζει καθόλου λειτουργικότητα.
       ========================================================= */

    [data-testid="stSidebar"] {
        background: #f8fafc !important;
        border-right: 1px solid #e2e8f0 !important;
        box-shadow: 8px 0 24px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* Streamlit multipage menu:
       streamlit app / Gantt Dashboard / Management / Viber Export */
    [data-testid="stSidebarNav"] {
        padding-top: 0.3rem !important;
        padding-bottom: 0.8rem !important;
        border-bottom: 1px solid #e2e8f0 !important;
        margin-bottom: 1rem !important;
    }

    [data-testid="stSidebarNav"] ul {
        padding-left: 0 !important;
        gap: 0.25rem !important;
    }

    [data-testid="stSidebarNav"] li {
        margin: 0.15rem 0 !important;
    }

    [data-testid="stSidebarNav"] a {
        border-radius: 9px !important;
        padding: 0.50rem 0.60rem !important;
        color: #334155 !important;
        font-weight: 600 !important;
        text-decoration: none !important;
        transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
    }

    [data-testid="stSidebarNav"] a:hover {
        background: #e2e8f0 !important;
        color: #0f172a !important;
        transform: translateX(2px) !important;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebarNav"] a[aria-current="page"] {
        background: #e2e8f0 !important;
        color: #0f172a !important;
        font-weight: 800 !important;
        box-shadow: inset 3px 0 0 #334155, 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    /* Management εσωτερικό menu: st.sidebar.radio σαν HTML menu buttons */
    [data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 0.35rem !important;
        display: flex !important;
        flex-direction: column !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label {
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 9px !important;
        padding: 0.55rem 0.65rem !important;
        margin: 0.05rem 0 !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
        cursor: pointer !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background: #f1f5f9 !important;
        border-color: #94a3b8 !important;
        transform: translateX(2px) !important;
        box-shadow: 0 4px 10px rgba(15, 23, 42, 0.10) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background: #e2e8f0 !important;
        border-color: #94a3b8 !important;
        box-shadow: inset 3px 0 0 #334155, 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
        color: #0f172a !important;
        font-weight: 800 !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] input {
        display: none !important;
    }

    /* Sidebar titles / text */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1e293b !important;
        letter-spacing: 0.02em !important;
    }

    [data-testid="stSidebar"] hr {
        margin: 1rem 0 !important;
        border-color: #e2e8f0 !important;
    }

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label {
        color: #334155;
    }

    /* Streamlit buttons μέσα στη sidebar: Undo / Redo / Refresh / Logout */
    [data-testid="stSidebar"] .stButton > button {
        width: 100% !important;
        border-radius: 9px !important;
        border: 1px solid #cbd5e1 !important;
        background: #ffffff !important;
        color: #334155 !important;
        font-weight: 700 !important;
        min-height: 2.35rem !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
    }

    [data-testid="stSidebar"] .stButton > button:hover:not(:disabled) {
        background: #f1f5f9 !important;
        border-color: #94a3b8 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 10px rgba(15, 23, 42, 0.10) !important;
    }

    [data-testid="stSidebar"] .stButton > button:disabled {
        opacity: 0.45 !important;
        background: #f8fafc !important;
        color: #94a3b8 !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stAlert"] {
        border-radius: 10px !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
    }

    .stPlotlyChart {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
    }

    .leave-conflict-box {
        padding: 12px;
        border-radius: 8px;
        background-color: #fee2e2;
        border: 1px solid #ef4444;
        margin-bottom: 8px;
        color: #b91c1c;
        font-weight: 500;
    }

    .hidden-btn-container {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # --- SMART POLLING SETUP ---
    # Το app δεν κάνει πλέον τυφλό rerun κάθε 30 δευτερόλεπτα.
    # Διαβάζει πρώτα το app_sync_state.last_changed_at από Supabase
    # και πατάει το κρυφό refresh μόνο αν υπάρχει πραγματική αλλαγή.
    supabase_url = ""
    supabase_anon_key = ""
    current_sync_stamp = ""

    try:
        supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
        supabase_anon_key = str(st.secrets.get("SUPABASE_ANON_KEY", ""))
    except Exception:
        supabase_url = ""
        supabase_anon_key = ""

    try:
        if utils.supabase:
            sync_res = (
                utils.supabase
                .table("app_sync_state")
                .select("last_changed_at")
                .eq("id", "global")
                .limit(1)
                .execute()
            )
            sync_rows = sync_res.data or []
            if sync_rows:
                current_sync_stamp = str(sync_rows[0].get("last_changed_at") or "")
    except Exception as e:
        print(f"Smart polling sync-state read failed: {e}")
        current_sync_stamp = ""

    polling_js = f"""
    (function () {{
        const SUPABASE_URL = {json.dumps(supabase_url)};
        const SUPABASE_ANON_KEY = {json.dumps(supabase_anon_key)};
        const CURRENT_SYNC_STAMP = {json.dumps(current_sync_stamp)};
        const STORAGE_KEY = "staff_pro_app_sync_state_last_changed_at";
        const DEBUG_ENABLED = true;

        function updateSmartPollingDebug(status, details) {{
            if (!DEBUG_ENABLED) return;
            let box = doc.getElementById("staff_pro_smart_polling_debug");
            if (!box) {{
                box = doc.createElement("div");
                box.id = "staff_pro_smart_polling_debug";
                doc.body.appendChild(box);
                box.style.cssText = "position: fixed; right: 20px; top: 58px; z-index: 999999; background: #0f172a; color: #e2e8f0; font-family: monospace; font-size: 11px; line-height: 1.35; padding: 8px 10px; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.35); max-width: 420px; opacity: 0.92; white-space: pre-wrap;";
            }}
            const now = new Date().toLocaleTimeString("el-GR", {{hour12: false}});
            box.textContent = "Smart Polling: " + status + "\\n" + now + "\\n" + (details || "");
        }}

        updateSmartPollingDebug("loaded", "current=" + (CURRENT_SYNC_STAMP || "-"));


        if (CURRENT_SYNC_STAMP) {{
            window.staffProCurrentSyncStamp = CURRENT_SYNC_STAMP;
            try {{
                window.localStorage.setItem(STORAGE_KEY, CURRENT_SYNC_STAMP);
            }} catch (e) {{}}
        }}

        if (window.staffProSmartPollingStarted) return;
        window.staffProSmartPollingStarted = true;

        let checkInFlight = false;

        function userIsWorking() {{
            // Δεν μπλοκάρουμε πλέον το refresh απλώς επειδή υπάρχει ανοιχτή φόρμα/μπάρα.
            // Το μπλοκάρουμε μόνο όταν ο χρήστης όντως γράφει ή έχει ενεργό πεδίο.
            const active = doc.activeElement;
            if (active) {{
                const tag = (active.tagName || "").toLowerCase();
                const role = active.getAttribute ? (active.getAttribute("role") || "") : "";
                if (["input", "textarea", "select"].includes(tag)) return true;
                if (["combobox", "listbox", "textbox", "spinbutton", "slider"].includes(role)) return true;
                if (active.isContentEditable) return true;
            }}

            return false;
        }}

        function clickCheckUpdates() {{
            const buttons = doc.querySelectorAll("button");
            for (let btn of buttons) {{
                const txt = (btn.innerText || btn.textContent || "").trim();
                if (txt.includes("🔄 Check Updates") || txt.includes("Check Updates")) {{
                    btn.click();
                    return true;
                }}
            }}
            updateSmartPollingDebug("button not found", "Could not find hidden Check Updates button");
            return false;
        }}

        async function checkForRemoteChanges() {{
            if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {{ updateSmartPollingDebug("disabled", "Missing SUPABASE_URL or SUPABASE_ANON_KEY"); return; }}
            if (userIsWorking()) {{ updateSmartPollingDebug("paused", "User is typing / active field"); return; }}
            if (checkInFlight) {{ updateSmartPollingDebug("waiting", "Previous check still running"); return; }}

            checkInFlight = true;
            try {{
                const response = await fetch(
                    SUPABASE_URL + "/rest/v1/app_sync_state?id=eq.global&select=last_changed_at",
                    {{
                        method: "GET",
                        headers: {{
                            "apikey": SUPABASE_ANON_KEY,
                            "Authorization": "Bearer " + SUPABASE_ANON_KEY,
                            "Accept": "application/json"
                        }},
                        cache: "no-store"
                    }}
                );

                if (!response.ok) {{ updateSmartPollingDebug("supabase fail", "HTTP " + response.status); return; }}

                const rows = await response.json();
                const remoteStamp = rows && rows[0] ? (rows[0].last_changed_at || "") : "";
                if (!remoteStamp) {{ updateSmartPollingDebug("no remote stamp", "Supabase returned no timestamp"); return; }}

                let localStamp = "";
                try {{
                    localStamp = window.localStorage.getItem(STORAGE_KEY) || "";
                }} catch (e) {{
                    localStamp = "";
                }}

                updateSmartPollingDebug("checked", "remote=" + remoteStamp + "\\nlocal=" + (localStamp || "-"));

                if (!localStamp) {{
                    try {{
                        window.localStorage.setItem(STORAGE_KEY, remoteStamp);
                    }} catch (e) {{}}
                    window.staffProCurrentSyncStamp = remoteStamp;
                    return;
                }}

                if (remoteStamp !== localStamp) {{
                    updateSmartPollingDebug("change found", "remote=" + remoteStamp + "\\nlocal=" + localStamp);
                    const clicked = clickCheckUpdates();
                    if (clicked) {{
                        updateSmartPollingDebug("refresh clicked", "Remote change detected");
                        try {{
                            window.localStorage.setItem(STORAGE_KEY, remoteStamp);
                        }} catch (e) {{}}
                        window.staffProCurrentSyncStamp = remoteStamp;
                    }}
                }}
            }} catch (e) {{
                updateSmartPollingDebug("error", String(e));
                console.warn("STAFF.PRO smart polling check failed", e);
            }} finally {{
                checkInFlight = false;
            }}
        }}

        setInterval(checkForRemoteChanges, 30000);
        setTimeout(checkForRemoteChanges, 3000);
    }})();
    """ if not show_menu else ""
    
    components.html("""
    <script>
    const doc = window.parent.document;
    
    // 1. Ψηφιακό Ρολόι
    let clockDiv = doc.getElementById("staff_pro_clock");
    if (!clockDiv) {
        clockDiv = doc.createElement("div");
        clockDiv.id = "staff_pro_clock";
        doc.body.appendChild(clockDiv);
        clockDiv.style.cssText = "position: fixed; top: 12px; right: 300px; font-size: 18px; font-weight: bold; color: #1e293b; z-index: 999999; background: #ffffff; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #cbd5e1; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;";
    }
    function updateClock() {
        const now = new Date();
        const dateOptions = { day: 'numeric', month: 'long', year: 'numeric' };
        clockDiv.innerHTML = now.toLocaleDateString('el-GR', dateOptions) + " | " + now.toLocaleTimeString('el-GR', {hour12: false});
    }
    updateClock();
    setInterval(updateClock, 1000);

    // 2. Εναλλασσόμενα Εικονίδια Καθαριότητας
    let loaderDiv = doc.getElementById("staff_pro_cleaner");
    if (!loaderDiv) {
        loaderDiv = doc.createElement("div");
        loaderDiv.id = "staff_pro_cleaner";
        doc.body.appendChild(loaderDiv);
        loaderDiv.style.cssText = "position: fixed; top: 12px; right: 20px; font-size: 20px; font-weight: bold; color: #334155; z-index: 999999; display: none; background: #f8fafc; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #cbd5e1; font-family: sans-serif; letter-spacing: 1px;";
    }
    
    const cleaningIcons = ["🧹", "🪣", "🧼", "🧽"];
    let cIdx = 0;
    setInterval(() => {
        loaderDiv.innerText = "Ανανέωση " + cleaningIcons[cIdx];
        cIdx = (cIdx + 1) % cleaningIcons.length;
    }, 400);

    let refreshBadgeTimer = null;
    setInterval(() => {
        const isRunning = doc.querySelector('[data-testid="stStatusWidget"]');
        if (isRunning) {
            if (!refreshBadgeTimer && loaderDiv.style.display !== 'block') {
                refreshBadgeTimer = setTimeout(() => {
                    loaderDiv.style.display = 'block';
                    refreshBadgeTimer = null;
                }, 900);
            }
        } else {
            if (refreshBadgeTimer) {
                clearTimeout(refreshBadgeTimer);
                refreshBadgeTimer = null;
            }
            loaderDiv.style.display = 'none';
        }
    }, 150);

    """ + polling_js + """
    </script>
    """, height=0, width=0)

    st.sidebar.title("STAFF.PRO")
    st.sidebar.write("---")
    
    selected_menu = None
    if show_menu and menu_options:
        selected_menu = st.sidebar.radio("Μενού Επιλογών", menu_options)
        st.sidebar.write("---")
    
    col_u, col_r = st.sidebar.columns(2)
    with col_u:
        if st.button("⏪ Undo", disabled=len(st.session_state.get('undo_stack', [])) == 0, use_container_width=True):
            utils.perform_undo()
            st.rerun()
    with col_r:
        if st.button("⏩ Redo", disabled=len(st.session_state.get('redo_stack', [])) == 0, use_container_width=True):
            utils.perform_redo()
            st.rerun()
            
    st.sidebar.write("---")
    st.sidebar.subheader("Κατάσταση Συστήματος")
    if utils.supabase:
        st.sidebar.success("☁️ Cloud Sync (Incremental)")
        
        st.sidebar.markdown('<div class="hidden-btn-container">', unsafe_allow_html=True)
        if st.sidebar.button("🔄 Check Updates", key="hidden_silent_refresh_btn"):
            st.session_state.last_sync_time = None
            st.rerun()
        st.sidebar.markdown('</div>', unsafe_allow_html=True)
        
        if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
            st.session_state.last_sync_time = None 
            st.rerun()
    else:
        st.sidebar.error("🔌 Εκτός Σύνδεσης (Τοπικά)")
        
    if not utils.SUPABASE_INSTALLED:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Κάνε Reboot την εφαρμογή.")
    elif not utils.HAS_SECRETS:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY).")

    st.sidebar.write("---")
    st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
    if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
        # Καθαρό logout: δεν αφήνουμε cached δεδομένα/χρόνους sync
        # να περάσουν στον επόμενο χρήστη στο ίδιο browser/session.
        for key in [
            "last_sync_time",
            "full_sync_done_for_user",
            "employees",
            "projects",
            "assignments",
            "leaves",
            "recurring_patterns",
            "evaluations",
            "emp_map",
            "proj_map",
            "assignments_by_date",
            "leaves_by_emp",
            "data_dirty",
        ]:
            st.session_state.pop(key, None)

        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.switch_page("streamlit_app.py")

    today_date = date.today()
    orphan_count = 0
    orphan_details = []
    for i in range(8):
        check_d = today_date + timedelta(days=i)
        day_assigns = st.session_state.get('assignments_by_date', {}).get(check_d, [])
        for a in day_assigns:
            if not a.get('employeeId') and not a.get('is_cancelled', False):
                orphan_count += 1
                proj = utils.get_project_info(a['projectId'])
                proj_name = proj.get('name', "Άγνωστο Έργο") if proj else "Άγνωστο Έργο"
                orphan_details.append(f"🔴 **{check_d.strftime('%d/%m/%Y')}** | Ώρες: {str(a.get('startTime', ''))[:5]}-{str(a.get('endTime', ''))[:5]} | Έργο: **{proj_name}**")
    
    if orphan_count > 0:
        st.error(f"⚠️ **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές (χωρίς προσωπικό)!**")
        with st.expander("🔍 Δείτε αναλυτικά τις ορφανές βάρδιες"):
            for detail in orphan_details:
                st.markdown(detail)
        st.write("---")

    return selected_menu
