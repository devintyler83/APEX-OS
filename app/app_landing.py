"""
app_landing.py — renders the APEX OS marketing landing page inside Streamlit.

Activated by setting the environment variable APEXOS_SHOW_LANDING=true before
launching the app.  The landing page is read fresh from disk each run so updates
to web/apexos-landing.html are reflected without restarting the server.
"""

import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_LANDING_HTML = Path(__file__).parent.parent / "web" / "apexos-landing.html"


def is_enabled() -> bool:
    return os.environ.get("APEXOS_SHOW_LANDING", "").lower() == "true"


def render() -> bool:
    """
    Render the landing page.  Returns True if the user has clicked through
    to the board, False if the landing page is still showing.
    """
    if "landing_dismissed" not in st.session_state:
        st.session_state.landing_dismissed = False

    if st.session_state.landing_dismissed:
        return True

    html = _LANDING_HTML.read_text(encoding="utf-8")
    components.html(html, height=900, scrolling=True)

    st.markdown("---")
    if st.button("Continue to APEX Board →", type="primary", use_container_width=False):
        st.session_state.landing_dismissed = True
        st.rerun()

    return False
