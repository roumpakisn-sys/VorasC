import io

import pandas as pd
import streamlit as st


def render_gantt_export(export_data, start_of_week):
    """Render της ενότητας συμβουλών και εξαγωγής Excel για το Gantt."""
    hint_text = "💡 *Συμβουλές:* **1)** Κάντε κλικ σε μια μπάρα για επεξεργασία. **2)** Κρατήστε αριστερό κλικ και κάντε drag μέσα στο gantt για κίνηση δεξιά/αριστερά. **3)** Σύρετε με τη ροδέλα πάνω-κάτω για τις ημέρες. **4)** Ρυθμίστε το κάθετο μέγεθος από το slider 'Ύψος Gantt'."

    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint:
            st.caption(hint_text)
        with col_btn:
            df_export = pd.DataFrame(export_data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_export.to_excel(writer, index=False, sheet_name="Πρόγραμμα")
            st.download_button(
                label="📥 Εξαγωγή (Excel)",
                data=buffer.getvalue(),
                file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.caption(hint_text)
