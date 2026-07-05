"""
Turns raw OCR/extracted text into a list of question dicts.

Because Kaplan / Wiley / CFAI mocks all format questions slightly
differently, this is intentionally a "best effort" parser. It is expected
that you will fix a handful of rows in the review table after parsing -
that's faster and safer than trying to build a perfect universal parser.

Supports two question numbering styles seen across providers:
  Style A: "1. <question text>"           (numbered-list style)
  Style B: "Question 1" on its own line   (CFA Institute "Premium Mock" style)

And two answer-key styles:
  Style A: "1. B" / "1) B"                (inline number + letter)
  Style B: "Answer 1" on its own line, followed by the correct option's
           full text on the next line, e.g. "Answer 1\nA. No"
"""
import re

# ---------- Question patterns ----------

# Style A: "1.", "Q1.", "Question 1." at the start of a line, followed by text on the same line
NUMBERED_ITEM_PATTERN = re.compile(
    r"^\s*(?:Q(?:uestion)?\.?\s*)?(\d{1,3})[\.\)]\s+", re.MULTILINE
)

# Style B: "Question 1" alone on its own line (no trailing period), text starts on the next line
QUESTION_HEADER_PATTERN = re.compile(r"^\s*Question\s+(\d{1,3})\s*$", re.MULTILINE)

# Matches an option line, e.g. "A. text", "(A) text", "A) text"
OPTION_PATTERN = re.compile(r"^\s*\(?([ABC])\)?[\.\)]\s+(.*)", re.MULTILINE)

# ---------- Answer key patterns ----------

# Style A: "1. B", "1) B", "1 - B", "1: B" all on one line
ANSWER_KEY_LINE = re.compile(r"^\s*(\d{1,3})[\.\)\-:]?\s*([ABC])\s*$", re.MULTILINE)
ANSWER_KEY_LINE_LOOSE = re.compile(r"(\d{1,3})\s*[\.\)\-:]\s*([ABC])\b")

# Style B: "Answer 1" alone on its own line
ANSWER_HEADER_PATTERN = re.compile(r"^\s*Answer\s+(\d{1,3})\s*$", re.MULTILINE)

# ---------- Session-splitting pattern (for combined 2-session PDFs) ----------

SESSION_SECTION_PATTERN = re.compile(r"Session\s*(\d)[\s\-]*(Questions|Answers)", re.IGNORECASE)


def parse_questions(raw_text: str):
    """
    Splits raw text into a list of question dicts:
    {q_number, question_text, option_a, option_b, option_c, correct_answer: None, topic: None}

    Tries "Question N" header style first (since it's unambiguous), and falls
    back to "N." numbered-list style if that style isn't found.
    """
    header_matches = list(QUESTION_HEADER_PATTERN.finditer(raw_text))
    if len(header_matches) >= 3:
        return _parse_with_pattern(raw_text, header_matches)

    numbered_matches = list(NUMBERED_ITEM_PATTERN.finditer(raw_text))
    return _parse_with_pattern(raw_text, numbered_matches)


def _parse_with_pattern(raw_text, matches):
    questions = []
    for idx, m in enumerate(matches):
        q_num = int(m.group(1))
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)
        block = raw_text[start:end].strip()

        option_matches = list(OPTION_PATTERN.finditer(block))

        # Skip blocks that don't look like real MCQs (e.g. table-of-contents lines,
        # section headers, or page numbers that happen to start with a digit).
        # A genuine CFA question has at least 2 of the 3 options present.
        if len(option_matches) < 2:
            continue

        stem = block[: option_matches[0].start()].strip()
        opts = _extract_options(block, option_matches)

        questions.append({
            "q_number": q_num,
            "question_text": stem,
            "option_a": opts.get("A", ""),
            "option_b": opts.get("B", ""),
            "option_c": opts.get("C", ""),
            "correct_answer": None,
            "topic": None,
        })

    # Sort and dedupe by q_number, keep first occurrence
    seen = {}
    for q in questions:
        if q["q_number"] not in seen:
            seen[q["q_number"]] = q
    return [seen[k] for k in sorted(seen.keys())]


def _extract_options(block, option_matches):
    opts = {"A": "", "B": "", "C": ""}
    for oi, om in enumerate(option_matches):
        letter = om.group(1)
        opt_start = om.start()
        opt_end = option_matches[oi + 1].start() if oi + 1 < len(option_matches) else len(block)
        full_opt = block[opt_start:opt_end]
        text = re.sub(r"^\s*\(?[ABC]\)?[\.\)]\s+", "", full_opt).strip()
        opts[letter] = text
    return opts


def parse_answer_key(raw_text: str):
    """
    Returns a dict {q_number: 'A'/'B'/'C'} parsed from an answer-key style text
    (either a standalone answer key PDF, or a section of a combined mock PDF).

    Tries "Answer N" header style first, falls back to inline "N. B" style.
    """
    answers = {}
    header_matches = list(ANSWER_HEADER_PATTERN.finditer(raw_text))
    if len(header_matches) >= 3:
        for idx, m in enumerate(header_matches):
            q_num = int(m.group(1))
            start = m.end()
            end = header_matches[idx + 1].start() if idx + 1 < len(header_matches) else len(raw_text)
            block = raw_text[start:end]
            letter_match = re.search(r"^\s*\(?([ABC])\)?[\.\)]\s+", block, re.MULTILINE)
            if letter_match:
                answers[q_num] = letter_match.group(1)
        if answers:
            return answers

    for m in ANSWER_KEY_LINE.finditer(raw_text):
        answers[int(m.group(1))] = m.group(2)
    if len(answers) < 5:  # fall back to a looser pattern if strict one found almost nothing
        for m in ANSWER_KEY_LINE_LOOSE.finditer(raw_text):
            q = int(m.group(1))
            answers.setdefault(q, m.group(2))
    return answers


def merge_answer_key(questions, answer_map):
    for q in questions:
        if q["q_number"] in answer_map:
            q["correct_answer"] = answer_map[q["q_number"]]
    return questions


def split_into_sessions(raw_text: str):
    """
    Attempts to detect a combined PDF containing multiple sessions, each with
    a Questions section and an Answers section, using running headers like
    'Mock Exam 1 Session 1 - Questions' / 'Mock Exam 1 Session 1- Answers'.

    Returns a dict like:
        {1: {"questions_text": "...", "answers_text": "..."},
         2: {"questions_text": "...", "answers_text": "..."}}
    or None if no such structure is detected (caller should treat the whole
    PDF as a single section instead).
    """
    raw_matches = list(SESSION_SECTION_PATTERN.finditer(raw_text))
    if not raw_matches:
        return None

    # Table-of-contents rows look like "...Session 1- Questions    3 - 25" -
    # i.e. immediately followed by a page-range number. Real section dividers
    # (either the big standalone divider page, or the running header repeated
    # on every content page) are never followed by a page range like that.
    # Filter those out so we don't split on TOC entries.
    page_range_after = re.compile(r"^\s*\d{1,4}\s*[-\u2013]\s*\d{1,4}")
    content_matches = []
    for m in raw_matches:
        following = raw_text[m.end(): m.end() + 25]
        if page_range_after.match(following):
            continue
        content_matches.append(m)

    # Fall back to unfiltered matches if filtering left nothing useful
    # (shouldn't normally happen, but avoids silently returning None).
    use_matches = content_matches if content_matches else raw_matches

    matches = [(m.start(), int(m.group(1)), m.group(2).lower()) for m in use_matches]

    first_positions = {}
    for pos, sess, typ in matches:
        key = (sess, typ)
        if key not in first_positions:
            first_positions[key] = pos

    # Need at least a Questions and Answers marker to be useful
    types_found = {typ for (_, typ) in first_positions}
    if "questions" not in types_found or "answers" not in types_found:
        return None

    ordered = sorted(first_positions.items(), key=lambda kv: kv[1])
    regions = {}
    for i, ((sess, typ), pos) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(raw_text)
        key_name = "questions_text" if typ == "questions" else "answers_text"
        regions.setdefault(sess, {})[key_name] = raw_text[pos:end]

    return regions


def parse_combined_mock(raw_text: str):
    """
    High-level helper: given the full text of a combined multi-session PDF,
    returns {session_number: [question_dicts_with_answers_merged]} if the
    session structure was detected, or None if this looks like a single
    section (caller should fall back to parse_questions/parse_answer_key
    directly on the whole text).
    """
    regions = split_into_sessions(raw_text)
    if not regions:
        return None

    result = {}
    for sess, parts in regions.items():
        q_text = parts.get("questions_text", "")
        a_text = parts.get("answers_text", "")
        questions = parse_questions(q_text)
        answer_map = parse_answer_key(a_text) if a_text else {}
        questions = merge_answer_key(questions, answer_map)
        result[sess] = questions
    return result
