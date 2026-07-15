import streamlit as st
import pandas as pd
from utils import db, parser
from utils.ocr_extract import full_text

st.set_page_config(page_title="Upload Topic Set", page_icon="📚", layout="wide")
db.init_db()

st.title("📚 Upload a Subject-Wise Question Set")
st.caption(
    "Separate from mocks — use this for topic-focused practice (e.g. a QBank export for one "
    "subject). Upload a PDF with questions and an answer key (embedded or separate). If the key "
    "includes a written rationale per question, it's captured and shown to you after you finish "
    "practicing, next to any question you got wrong. This isn't timed."
)

mode = st.radio("What are you doing?", ["Create a new topic set", "Add questions to an existing set"], horizontal=True)

topic_set_id = None

if mode == "Create a new topic set":
    with st.form("new_topic_set_form"):
        name = st.text_input("Set name", placeholder="e.g. Quantitative Methods - Kaplan QBank")
        subject = st.text_input("Subject / topic (optional)", placeholder="e.g. Quantitative Methods")
        submitted = st.form_submit_button("Create set & continue to upload →")
    if submitted:
        if not name.strip():
            st.error("Please give the set a name.")
            st.stop()
        topic_set_id = db.create_topic_set(name.strip(), subject.strip() or None)
        st.session_state["active_topic_set_id"] = topic_set_id
        st.success(f"Set '{name}' created. Now upload its questions below.")

    if "active_topic_set_id" in st.session_state and mode == "Create a new topic set":
        topic_set_id = st.session_state["active_topic_set_id"]

else:
    sets = [dict(t) for t in db.list_topic_sets()]
    if not sets:
        st.info("No topic sets exist yet — create one first.")
        st.stop()
    choice = st.selectbox("Select topic set", sets, format_func=lambda t: f"{t['name']} ({t['subject'] or 'n/a'})")
    topic_set_id = choice["id"]

st.divider()

if topic_set_id:
    t = db.get_topic_set(topic_set_id)
    st.subheader(f"Uploading to: **{t['name']}**")

    col1, col2 = st.columns(2)
    with col1:
        q_pdf = st.file_uploader("Question paper (PDF)", type=["pdf"], key=f"topic_pdf_{topic_set_id}")
    with col2:
        a_pdf = st.file_uploader("Answer key (PDF) — optional, only if it's a separate file",
                                  type=["pdf"], key=f"topic_ans_pdf_{topic_set_id}")

    if q_pdf and st.button("🔍 Extract questions", type="primary"):
        with st.spinner("Reading PDF (using OCR automatically for scanned pages)... this can take a minute"):
            progress = st.progress(0.0)
            raw_text, used_ocr = full_text(q_pdf.read(), progress_callback=lambda p: progress.progress(p))
            progress.empty()

        if used_ocr:
            st.info("Some pages were scanned images — OCR was used to read them. Please double check the questions below.")

        raw_text_clean = parser.strip_header_noise(raw_text)
        questions = parser.parse_questions(raw_text_clean)

        if a_pdf:
            ans_text, _ = full_text(a_pdf.read())
            answer_map = parser.parse_answer_key_with_explanations(parser.strip_header_noise(ans_text))
        else:
            # maybe the answer key is embedded further down in the same PDF
            tail = parser.find_embedded_answer_key(raw_text_clean)
            answer_map = parser.parse_answer_key_with_explanations(tail)

        questions = parser.merge_answer_key_with_explanations(questions, answer_map)

        st.session_state[f"parsed_topic_questions_{topic_set_id}"] = questions
        st.success(
            f"Extracted {len(questions)} questions, "
            f"{sum(1 for q in questions if q['correct_answer'])} with answers matched, "
            f"{sum(1 for q in questions if q.get('explanation'))} with an explanation."
        )

    session_key = f"parsed_topic_questions_{topic_set_id}"
    if session_key in st.session_state:
        st.subheader("Review & fix before saving")
        st.caption("Fix any misread text/options/answers, and add or edit explanations, before saving.")

        if not st.session_state[session_key]:
            st.warning(
                "No questions could be detected in this PDF. Check that it has clearly numbered "
                "questions with A/B/C options."
            )
            st.stop()

        df = pd.DataFrame(st.session_state[session_key])
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
                "explanation": st.column_config.TextColumn("Explanation (shown for wrong answers)", width="large"),
                "topic": None,
            },
            key=f"topic_editor_{topic_set_id}",
        )

        missing = edited["correct_answer"].isna().sum() + (edited["correct_answer"] == "").sum()
        if missing:
            st.warning(f"{missing} question(s) still have no correct answer set.")

        if st.button("💾 Save these questions", type="primary"):
            questions_to_save = edited.to_dict("records")
            excluded_nums = []
            for q in questions_to_save:
                q.pop("topic", None)
                if not q.get("correct_answer"):
                    q["correct_answer"] = None
                if not q.get("explanation"):
                    q["explanation"] = None
                if db.is_question_incomplete(q):
                    q["active"] = 0
                    excluded_nums.append(q.get("q_number"))
                else:
                    q["active"] = 1
            db.bulk_insert_topic_questions(topic_set_id, questions_to_save)
            del st.session_state[session_key]
            if excluded_nums:
                st.warning(
                    f"Saved {len(questions_to_save)} questions, but {len(excluded_nums)} had missing "
                    f"text/options/answer and were excluded from practice so they won't interrupt you: "
                    f"Q{', Q'.join(str(n) for n in excluded_nums)}. They're still saved — fix and "
                    "re-include them anytime in the 'Fix excluded questions' section below."
                )
            else:
                st.success(f"Saved {len(questions_to_save)} questions. "
                           "Go to **Practice by Topic** in the sidebar when you're ready.")
            st.balloons()

if topic_set_id:
    st.divider()
    st.subheader("🔧 Fix excluded questions")
    st.caption(
        "Questions saved but excluded for missing data live here. Fix a row and it rejoins "
        "practice next time you save."
    )
    excluded = [dict(q) for q in db.get_excluded_topic_questions(topic_set_id)]
    if not excluded:
        st.caption("No excluded questions for this set right now.")
    else:
        edf = pd.DataFrame(excluded)
        edited_excluded = st.data_editor(
            edf,
            use_container_width=True,
            column_config={
                "id": None,
                "topic_set_id": None,
                "active": None,
                "q_number": st.column_config.NumberColumn("Q#", disabled=True),
                "question_text": st.column_config.TextColumn("Question", width="large"),
                "option_a": st.column_config.TextColumn("Option A", width="medium"),
                "option_b": st.column_config.TextColumn("Option B", width="medium"),
                "option_c": st.column_config.TextColumn("Option C", width="medium"),
                "correct_answer": st.column_config.SelectboxColumn("Correct answer", options=["A", "B", "C", None]),
                "explanation": st.column_config.TextColumn("Explanation", width="large"),
            },
            hide_index=True,
            key=f"fix_excluded_topic_{topic_set_id}",
        )
        if st.button("✅ Save fixes & re-include completed ones", key=f"reinclude_topic_{topic_set_id}"):
            rows = edited_excluded.to_dict("records")
            reincluded = 0
            for r in rows:
                complete = not db.is_question_incomplete(r)
                db.update_topic_question(
                    r["id"], r["question_text"], r["option_a"], r["option_b"], r["option_c"],
                    r.get("correct_answer") or None, r.get("explanation") or None, 1 if complete else 0,
                )
                reincluded += complete
            st.success(f"{reincluded} of {len(rows)} question(s) fixed and re-included in practice.")
            st.rerun()
