"""Verity AI - Streamlit entry point."""
from dataclasses import replace

import os

import streamlit as st

from verity.config import load_settings
from verity.db import AuditDB
from verity.ui import pages
from verity.ui.theme import CSS

st.set_page_config(page_title="Verity AI · Fact-Check Intelligence", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="auto")
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def _db(path: str) -> AuditDB:
    d = AuditDB(path)
    try:
        d.purge(int(os.environ.get('VERITY_RETENTION_DAYS', '30') or 30))
    except Exception:
        pass
    return d


settings = load_settings()
ws = pages.workspace_id()
db = _db(settings.db_path)
page, model = pages.sidebar(settings)
settings = replace(settings, model=model)

{
    "Fact-check": pages.page_check,
    "History": pages.page_history,
    "Analytics": pages.page_analytics,
    "Methodology": pages.page_method,
}[page](settings, db, ws)
