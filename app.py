import streamlit as st
import pandas as pd
from utils import db

st.set_page_config(page_title="CFA Level I Mock Exam Simulator", page_icon="📊", layout="wide")

db.init_db()

st.title("📊 CFA Level I Mock Exam Simulator")
st.caption("Upload mocks, sit them under real exam conditions, and track your progress across every paper.")

st.markdown("""
Use the sidebar to navigate:
- **📄 Upload Mock** — add a new mock PDF (and its answer key if separate)
- **📝 Take Exam** — sit a mock in a timed, exam-like interface
- **✅ Review** — review a completed attempt, question by question
""")

st.divider()

mocks = db.list_mocks()
attempts = db.list_attempts()

col1, col2, col3 = st.columns(3)
col1.metric("Mocks uploaded", len(mocks))
col2.metric("Sessions attempted", len([a for a in attempts if a["status"] == "completed"]))
col3.metric(
    "Average score",
    f"{sum(a['score'] for a in attempts if a['score'] is not None) / max(1, len([a for a in attempts if a['score'] is not None])):.0f}%"
    if any(a["score"] is not None for a in attempts) else "—",
)

st.subheader("Your mocks")
if not mocks:
    st.info("No mocks uploaded yet. Head to **Upload Mock** in the sidebar to add your first one.")
else:
    rows = []
    for m in mocks:
        mock_attempts = [a for a in attempts if a["mock_id"] == m["id"]]
        completed = [a for a in mock_attempts if a["status"] == "completed"]
        best = max([a["score"] for a in completed], default=None)
        rows.append({
            "Mock": m["name"],
            "Provider": m["provider"] or "—",
            "Sessions": m["num_sessions"],
            "Q per session": m["questions_per_session"],
            "Min per session": m["minutes_per_session"],
            "Attempts": len(mock_attempts),
            "Best score": f"{best}%" if best is not None else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.subheader("Recent attempts")
if not attempts:
    st.info("No attempts yet.")
else:
    rows = []
    for a in attempts[:15]:
        rows.append({
            "Mock": a["mock_name"],
            "Session": a["session_number"],
            "Status": a["status"],
            "Score": f"{a['score']}%" if a["score"] is not None else "—",
            "Started": a["start_time"][:16].replace("T", " "),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
