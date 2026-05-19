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
tab_auto, tab_ai = st.tabs(["🚀 Αυτόματο Μήνυμα (Γρήγορο)", "🤖 Δημιουργία με AI (Gemini / ChatGPT)"])

with tab_auto:
    st.info("Το παρακάτω μήνυμα παράγεται αυτόματα και είναι έτοιμο για αντιγραφή. Κάντε κλικ στο εικονίδιο αντιγραφής επάνω δεξιά στο πλαίσιο.")
    st.code(viber_msg, language="markdown")
    
with tab_ai:
    st.write("Αν θέλετε ένα πιο προσαρμοσμένο, έξυπνο κείμενο (π.χ. 'Καλημέρα ομάδα!'), μπορείτε να ζητήσετε από την τεχνητή νοημοσύνη (Gemini) να το γράψει για εσάς.")
    
    # Ασφαλής μετατροπή του κειμένου για το JavaScript
    raw_data_for_js = ai_prompt.replace('\n', '\\n').replace("'", "\\'").replace('"', '\\"')
    
    html_code = f"""
    <div id="ai-container" style="font-family: sans-serif;">
        <button id="gen-btn" style="background-color: #8e7cc3; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold;">
            ✨ Γράψε το με Gemini AI
        </button>
        <div id="loading" style="display:none; margin-top: 15px; color: #666;">⏳ Το AI σκέφτεται... παρακαλώ περιμένετε (διαρκεί λίγα δευτερόλεπτα)...</div>
        <div id="error" style="display:none; margin-top: 15px; color: #dc2626;"></div>
        <textarea id="ai-result" style="display:none; width: 100%; height: 300px; margin-top: 15px; padding: 10px; border-radius: 5px; border: 1px solid #ccc; font-family: monospace; resize: vertical;" readonly></textarea>
        <button id="copy-btn" style="display:none; margin-top: 10px; background-color: #16a34a; color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; font-weight: bold;">📋 Αντιγραφή Μηνύματος</button>
    </div>
    
    <script>
    document.getElementById('gen-btn').addEventListener('click', async () => {{
        const btn = document.getElementById('gen-btn');
        const loading = document.getElementById('loading');
        const resultArea = document.getElementById('ai-result');
        const errorArea = document.getElementById('error');
        const copyBtn = document.getElementById('copy-btn');
        
        btn.disabled = true;
        loading.style.display = 'block';
        resultArea.style.display = 'none';
        errorArea.style.display = 'none';
        copyBtn.style.display = 'none';
        
        const apiKey = ""; 
        const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key=${{apiKey}}`;
        
        const prompt = `{raw_data_for_js}`;
        
        const payload = {{
            contents: [{{ parts: [{{ text: prompt }}] }}],
            systemInstruction: {{ parts: [{{ text: "Είσαι ένας βοηθός διαχειριστή προσωπικού. Γράφεις πολύ φιλικά, ξεκάθαρα, και επαγγελματικά μηνύματα για το Viber. Χρησιμοποίησε κατάλληλα emojis. Μην είσαι φλύαρος." }}] }}
        }};
        
        const sleep = ms => new Promise(r => setTimeout(r, ms));
        const delays = [1000, 2000, 4000, 8000, 16000];
        let data = null;
        let success = false;
        
        for (let attempt = 0; attempt < 6; attempt++) {{
            try {{
                const response = await fetch(url, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                
                if (response.ok) {{
                    data = await response.json();
                    success = true;
                    break;
                }}
            }} catch (e) {{
                // Αγνοούμε τα σφάλματα δικτύου και ξαναπροσπαθούμε
            }}
            if (attempt < 5) await sleep(delays[attempt]);
        }}
        
        loading.style.display = 'none';
        btn.disabled = false;
        
        if (success && data && data.candidates && data.candidates[0].content) {{
            const text = data.candidates[0].content.parts[0].text;
            resultArea.value = text;
            resultArea.style.display = 'block';
            copyBtn.style.display = 'inline-block';
            
            copyBtn.onclick = () => {{
                resultArea.select();
                document.execCommand('copy');
                copyBtn.innerText = '✔️ Αντιγράφηκε!';
                setTimeout(() => copyBtn.innerText = '📋 Αντιγραφή Μηνύματος', 2000);
            }};
        }} else {{
            errorArea.innerText = "Δεν κατέστη δυνατή η σύνδεση με το AI. Χρησιμοποιήστε το έτοιμο κείμενο (Prompt) παρακάτω για το ChatGPT.";
            errorArea.style.display = 'block';
        }}
    }});
    </script>
    """
    
    import streamlit.components.v1 as components
    components.html(html_code, height=450)
    
    st.markdown("---")
    st.subheader("📝 Χειροκίνητη Αντιγραφή (Prompt)")
    st.info("Αν προτιμάτε να χρησιμοποιήσετε το **δικό σας ChatGPT**, αντιγράψτε το παρακάτω κείμενο και κάντε το επικόλληση εκεί.")
    st.code(ai_prompt, language="text")
