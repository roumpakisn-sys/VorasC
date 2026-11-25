from datetime import timedelta
from functools import partial
import io

import pandas as pd
import streamlit as st

from gantt_email import without_email_menu


def create_gantt_excel(export_data):
    df_export = pd.DataFrame(export_data)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Πρόγραμμα")
    return buffer.getvalue()


def render_gantt_export(export_data, start_of_week):
    """Render της ενότητας συμβουλών και εξαγωγής Excel για το Gantt."""
    hint_text = "💡 *Συμβουλές:* **1)** Κάντε κλικ σε μια μπάρα για επεξεργασία. **2)** Κρατήστε αριστερό κλικ και κάντε drag μέσα στο gantt για κίνηση δεξιά/αριστερά. **3)** Σύρετε με τη ροδέλα πάνω-κάτω για τις ημέρες. **4)** Ρυθμίστε το κάθετο μέγεθος από το slider 'Ύψος Gantt'."

    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint:
            st.caption(hint_text)
        with col_btn:
            st.download_button(
                label="📥 Εξαγωγή (Excel)",
                data=partial(create_gantt_excel, export_data),
                on_click="ignore",
                file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.caption(hint_text)


def render_gantt_html_export(html_chart, start_of_week):
    downloadable_gantt_html = f"""<!doctype html>
<html lang="el">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Gantt Πρόγραμμα - {start_of_week.strftime('%d/%m/%Y')}</title>
    <style>
        body {{
            margin: 0;
            padding: 18px;
            background: #f8fafc;
            font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
        }}
        .export-title {{
            margin: 0 0 12px 0;
            color: #0f172a;
            font-size: 22px;
            font-weight: 800;
        }}
        .export-subtitle {{
            margin: 0 0 18px 0;
            color: #475569;
            font-size: 14px;
        }}
        #gantt-master-container {{
            height: calc(100vh - 110px) !important;
            max-height: none !important;
        }}
    </style>
</head>
<body>
    <h1 class="export-title">Πρόγραμμα Gantt</h1>
    <div class="export-subtitle">
        Εβδομάδα: {start_of_week.strftime('%d/%m/%Y')} - {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}
    </div>
    {without_email_menu(html_chart)}
</body>
</html>
"""

    st.download_button(
        "🌐 Εξαγωγή Gantt σε HTML",
        data=downloadable_gantt_html.encode("utf-8"),
        on_click="ignore",
        file_name=f"gantt_programma_{start_of_week.strftime('%Y_%m_%d')}.html",
        mime="text/html",
        use_container_width=True,
    )
