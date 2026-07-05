import streamlit as st
import pandas as pd
from utils import db
import os

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
db.init_db()

st.title("📊 Progress Dashboard")

with st.expander("💾 Backup / Restore your data (important on Streamlit Cloud)"):
    st.caption(
        "Streamlit Community Cloud wipes the filesystem whenever the app restarts or you push new code. "
        "Download a backup after each study session, and restore it after a redeploy so you don't lose your mocks/progress."
    )
    b1, b2 = st.columns(2)
    with b1:
        if os.path.exists(db.DB_PATH):
            with open(db.DB_PATH, "rb") as f:
                st.download_button("⬇ Download backup (.db)", f, file_name="exam_data_backup.db")
    with b2:
        restore_file = st.file_uploader("⬆ Restore from backup", type=["db"], key="restore_uploader")
        if restore_file and st.button("Restore now (overwrites current data)"):
            with open(db.DB_PATH, "wb") as f:
                f.write(restore_file.read())
            st.success("Restored! Refresh the page.")


mocks = db.list_mocks()

with st.expander("🗑️ Manage / delete mocks"):
    if not mocks:
        st.caption("No mocks uploaded yet.")
    else:
        mocks_as_dicts = [dict(m) for m in mocks]
        mock_to_delete = st.selectbox(
            "Select a mock to delete",
            mocks_as_dicts,
            format_func=lambda m: f"{m['name']} ({m['provider'] or 'n/a'})",
            key="mock_delete_select",
        )
        st.caption("This permanently deletes the mock, all its questions, and all attempt history for it.")
        confirm = st.checkbox(f"I understand this will permanently delete '{mock_to_delete['name']}'", key="confirm_delete_mock")
        if st.button("🗑️ Delete this mock", type="primary", disabled=not confirm):
            db.delete_mock(mock_to_delete["id"])
            st.success(f"Deleted '{mock_to_delete['name']}'.")
            st.rerun()

attempts = db.list_attempts()
completed = [a for a in attempts if a["status"] == "completed"]

if not completed:
    st.info("No completed attempts yet — your progress will show up here after your first mock.")
    st.stop()

df = pd.DataFrame([{
    "Mock": a["mock_name"],
    "Session": a["session_number"],
    "Score": a["score"],
    "Date": a["start_time"][:10],
} for a in completed])

st.subheader("Score trend over time")
trend = df.sort_values("Date").reset_index(drop=True)
st.line_chart(trend.set_index("Date")["Score"])

st.subheader("Score by mock")
by_mock = df.groupby("Mock")["Score"].agg(["mean", "max", "count"]).reset_index()
by_mock.columns = ["Mock", "Average score", "Best score", "Attempts"]
st.dataframe(by_mock, use_container_width=True, hide_index=True)

st.subheader("Which mocks are fully solved")
rows = []
for m in mocks:
    m_attempts = [a for a in completed if a["mock_id"] == m["id"]]
    sessions_done = sorted(set(a["session_number"] for a in m_attempts))
    fully_done = len(sessions_done) >= m["num_sessions"]
    rows.append({
        "Mock": m["name"],
        "Sessions completed": f"{len(sessions_done)}/{m['num_sessions']}",
        "Fully solved": "✅" if fully_done else "—",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
