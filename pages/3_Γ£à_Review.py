import streamlit as st
from utils import db

st.set_page_config(page_title="Review", page_icon="✅", layout="wide")
db.init_db()

st.title("✅ Review Your Attempts")

attempts = [dict(a) for a in db.list_attempts() if a["status"] == "completed"]

just_finished = st.session_state.pop("last_completed_attempt_id", None)

if not attempts:
    st.info("No completed attempts yet. Take an exam first!")
    st.stop()

default_idx = 0
if just_finished:
    ids = [a["id"] for a in attempts]
    if just_finished in ids:
        default_idx = ids.index(just_finished)

attempt = st.selectbox(
    "Select attempt to review",
    attempts,
    index=default_idx,
    format_func=lambda a: f"{a['mock_name']} — Session {a['session_number']} — {a['start_time'][:16].replace('T',' ')} — Score: {a['score']}%",
)

review_rows = db.get_review_data(attempt["id"])

scored = [r for r in review_rows if r["correct_answer"]]
correct_count = sum(1 for r in scored if r["is_correct"])
answered_count = sum(1 for r in review_rows if r["selected_answer"])
unscored_count = len(review_rows) - len(scored)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Score", f"{attempt['score']}%")
c2.metric("Correct", f"{correct_count} / {len(scored)}")
c3.metric("Answered", f"{answered_count} / {len(review_rows)}")
c4.metric("No answer key on file", unscored_count)

st.divider()

filter_choice = st.radio("Show:", ["All questions", "Only wrong answers", "Only flagged", "Only unanswered"], horizontal=True)

for r in review_rows:
    if filter_choice == "Only wrong answers" and not (r["correct_answer"] and r["selected_answer"] and not r["is_correct"]):
        continue
    if filter_choice == "Only flagged" and not r["flagged"]:
        continue
    if filter_choice == "Only unanswered" and r["selected_answer"]:
        continue

    if r["correct_answer"] is None:
        status = "❔ No answer key"
        color = "gray"
    elif r["selected_answer"] is None:
        status = "⬜ Not answered"
        color = "orange"
    elif r["is_correct"]:
        status = "✅ Correct"
        color = "green"
    else:
        status = "❌ Incorrect"
        color = "red"

    with st.expander(f"Q{r['q_number']} — {status}" + ("  🚩" if r["flagged"] else "")):
        st.write(r["question_text"])
        for letter in ["A", "B", "C"]:
            text = r[f"option_{letter.lower()}"]
            if not text:
                continue
            tag = ""
            if letter == r["correct_answer"]:
                tag += " ✅ **Correct answer**"
            if letter == r["selected_answer"]:
                tag += " 👉 **Your answer**"
            st.markdown(f"**{letter}.** {text}{tag}")
        if r["topic"]:
            st.caption(f"Topic: {r['topic']}")
        if not r["is_correct"] and r["correct_answer"] and r["explanation"]:
            st.info(f"**Explanation:** {r['explanation']}")
