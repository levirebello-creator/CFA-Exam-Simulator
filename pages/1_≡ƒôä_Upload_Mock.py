import streamlit as st
import pandas as pd
from utils import db, parser
from utils.ocr_extract import full_text

st.set_page_config(page_title="Upload Mock", page_icon="📄", layout="wide")
db.init_db()

st.title("📄 Upload a Mock")
st.caption(
    "Since real mocks (CFAI / Kaplan / Wiley...) come as separate AM/PM papers, "
    "upload **one session at a time**. If a mock has 2 sessions, add the mock once, "
    "then come back here and add session 2 to the same mock."
)

mode = st.radio("What are you doing?", ["Create a new mock", "Add a session to an existing mock"], horizontal=True)

mock_id = None
session_number = 1

if mode == "Create a new mock":
    with st.form("new_mock_form"):
        name = st.text_input("Mock name", placeholder="e.g. Kaplan Mock 3 - 2026")
        provider = st.selectbox("Provider", ["CFA Institute", "Kaplan Schweser", "Wiley", "Other"])
        num_sessions = st.selectbox("How many sessions does this mock have?", [1, 2], index=1,
                                     help="The real Level I exam has 2 sessions (AM & PM) of 90 Q / 135 min each.")
        questions_per_session = st.number_input("Questions in this session", min_value=1, max_value=200, value=90)
        minutes_per_session = st.number_input("Minutes allowed for this session", min_value=1, max_value=300, value=135)
        submitted = st.form_submit_button("Create mock & continue to upload →")
    if submitted:
        if not name.strip():
            st.error("Please give the mock a name.")
            st.stop()
        mock_id = db.create_mock(name.strip(), provider, num_sessions, questions_per_session, minutes_per_session)
        st.session_state["active_mock_id"] = mock_id
        st.session_state["active_session_number"] = 1
        st.success(f"Mock '{name}' created. Now upload session 1 below.")

    if "active_mock_id" in st.session_state and mode == "Create a new mock":
        mock_id = st.session_state["active_mock_id"]
        session_number = st.session_state.get("active_session_number", 1)

else:
    mocks = [dict(m) for m in db.list_mocks()]
    if not mocks:
        st.info("No mocks exist yet — create one first.")
        st.stop()
    mock_choice = st.selectbox("Select mock", mocks, format_func=lambda m: f"{m['name']} ({m['provider'] or 'n/a'})")
    mock_id = mock_choice["id"]
    session_number = st.number_input("Session number to add/replace", min_value=1,
                                      max_value=int(mock_choice["num_sessions"]), value=1)

st.divider()

if mock_id:
    m = db.get_mock(mock_id)
    st.subheader(f"Uploading: **{m['name']}** — Session {session_number}")

    col1, col2 = st.columns(2)
    with col1:
        mock_pdf = st.file_uploader("Mock question paper (PDF)", type=["pdf"], key=f"mock_pdf_{mock_id}_{session_number}")
    with col2:
        answer_pdf = st.file_uploader("Answer key (PDF) — optional, only if it's a separate file",
                                       type=["pdf"], key=f"ans_pdf_{mock_id}_{session_number}")

    if mock_pdf and st.button("🔍 Extract questions", type="primary"):
        with st.spinner("Reading PDF (using OCR automatically for scanned pages)... this can take a minute for scanned mocks"):
            progress = st.progress(0.0)
            raw_text, used_ocr = full_text(mock_pdf.read(), progress_callback=lambda p: progress.progress(p))
            progress.empty()

        if used_ocr:
            st.info("Some pages were scanned images — OCR was used to read them. Please double check those questions carefully below.")

        questions = parser.parse_questions(raw_text)

        answer_map = {}
        if answer_pdf:
            ans_text, _ = full_text(answer_pdf.read())
            answer_map = parser.parse_answer_key(ans_text)
        else:
            # maybe the answer key is embedded at the tail of the same PDF
            tail = raw_text[int(len(raw_text) * 0.7):]
            answer_map = parser.parse_answer_key(tail)

        questions = parser.merge_answer_key(questions, answer_map)

        st.session_state[f"parsed_questions_{mock_id}_{session_number}"] = questions
        st.success(f"Extracted {len(questions)} questions, {sum(1 for q in questions if q['correct_answer'])} with answers matched.")

    key = f"parsed_questions_{mock_id}_{session_number}"
    if key in st.session_state:
        st.subheader("Review & fix before saving")
        st.caption("Fix any misread text/options and fill in missing correct answers (A/B/C). This is the most important step for exam-mixed providers.")

        df = pd.DataFrame(st.session_state[key])
        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "correct_answer": st.column_config.SelectboxColumn("Correct answer", options=["A", "B", "C", None]),
                "q_number": st.column_config.NumberColumn("Q#"),
                "question_text": st.column_config.TextColumn("Question", width="large"),
                "option_a": st.column_config.TextColumn("Option A", width="medium"),
                "option_b": st.column_config.TextColumn("Option B", width="medium"),
                "option_c": st.column_config.TextColumn("Option C", width="medium"),
                "topic": st.column_config.TextColumn("Topic (optional)"),
            },
            key=f"editor_{mock_id}_{session_number}",
        )

        missing = edited["correct_answer"].isna().sum() + (edited["correct_answer"] == "").sum()
        if missing:
            st.warning(f"{missing} question(s) still have no correct answer set. You can still save and fill these in later, "
                       "but review scoring will treat them as unanswerable.")

        if st.button("💾 Save this session to the database", type="primary"):
            questions_to_save = edited.to_dict("records")
            for q in questions_to_save:
                if not q.get("correct_answer"):
                    q["correct_answer"] = None
            db.bulk_insert_questions(mock_id, int(session_number), questions_to_save)
            del st.session_state[key]
            st.success(f"Saved {len(questions_to_save)} questions for session {session_number}. "
                       "Go to **Take Exam** in the sidebar when you're ready to sit it.")
            st.balloons()
