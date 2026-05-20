import streamlit as st


DEFAULT_PLOTLY_CONFIG = {
    "displayModeBar": True,
    "scrollZoom": False,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["zoom2d", "select2d", "lasso2d", "autoScale2d"],
}


def _extract_clicked_key(points):
    if not points:
        return None

    point = points[0]

    customdata = (
        point.get("customdata")
        or point.get("customData")
        or point.get("custom_data")
    )

    if isinstance(customdata, list) and customdata:
        clicked_key = customdata[0]
    else:
        clicked_key = customdata

    if clicked_key and clicked_key != "Empty":
        return clicked_key

    return None


def render_gantt_html(fig, height=650, key="html_gantt_chart"):
    """
    HTML/JS Plotly rendering με click event.

    Αν το streamlit-plotly-events δεν υπάρχει ή αποτύχει,
    γυρίζει αυτόματα στο υπάρχον st.plotly_chart ώστε να μη σπάσει η εφαρμογή.
    """

    try:
        from streamlit_plotly_events import plotly_events

        points = plotly_events(
            fig,
            click_event=True,
            select_event=False,
            hover_event=False,
            override_height=height,
            override_width="100%",
            key=key,
        )

        return _extract_clicked_key(points)

    except Exception:
        try:
            event = st.plotly_chart(
                fig,
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                config=DEFAULT_PLOTLY_CONFIG,
            )

            if event and "selection" in event and event["selection"].get("points"):
                cd = event["selection"]["points"][0].get("customdata", [None])[0]
                if cd and cd != "Empty":
                    return cd

        except Exception:
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

    return None
