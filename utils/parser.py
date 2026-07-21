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

# Style B: "Question 1" alone on its own line. Real-world OCR of exam PDFs
# very often glues stray noise onto the same line (a stray "|" from a table
# border, a misread trailing ":" or ".", or bleed-through text from an
# adjacent column) -- e.g. "Question 3 |" or "Question 14 Que". Requiring the
# line to be *exactly* "Question N" causes those headers to be silently
# skipped, which merges that whole question into the previous one. So we only
# require that "Question" isn't glued onto a preceding word (same tolerance
# OPTION_PATTERN uses below) and don't anchor the end of the line at all.
QUESTION_HEADER_PATTERN = re.compile(r"Question\s*(\d{1,3})\b", re.MULTILINE)

# Matches an option line, e.g. "A. text", "(A) text", "A) text"
# Tolerant of common OCR artifacts seen in real scans:
#   - comma misread in place of the period ("B,")
#   - the letter marker in lowercase ("c." instead of "C.")
#   - stray bleed-through text from an adjacent column glued onto the same
#     line before the marker ("Hoda is A. the nature..."), or a stray
#     leading symbol from a misread table border (": A. less than...") --
#     only requires that the letter isn't part of a longer word (i.e. not
#     directly preceded by another letter), not a true line start.
#
# Deliberately requires the punctuation to come *immediately* after the
# single option letter, with no stray letters tolerated in between. CFA
# question stems routinely contain "<Name>, CFA, ..." -- allowing even one
# or two stray letters between the letter and the punctuation lets "CFA,"
# itself match this pattern (letter "C" + "FA" + comma) and get mistaken for
# option C's marker, truncating the stem and clobbering the real options.
#
# Colon is deliberately NOT an accepted marker punctuation. Unlike the
# others, "letter + colon" collides constantly with ordinary English --
# "...is best described as a:", "...known as a:" -- where the lowercase
# word "a" followed by a colon reads exactly like an option-a marker. In
# real scans this false-positive was far more common than genuine "A:"
# markers (which are usually a misread "A." anyway).
OPTION_PATTERN = re.compile(r"(?<![A-Za-z])\(?([ABCabc])\)?[\.\)\,]\s+(.*)", re.MULTILINE)

# ---------- Noise patterns (OCR artifacts to strip before parsing) ----------

# Running headers/footers that repeat on every page and sometimes get OCR'd
# right into the middle of question or option text.
HEADER_NOISE_PATTERN = re.compile(
    r"Mock\s*Exam\s*\d+\s*Session\s*\d[\s\-]*(Questions|Answers)", re.IGNORECASE
)

# Some QBank-style providers repeat "of <total>" plus a redundant label line
# (and "Solution" for answers) right after "Question N"/"Answer N", e.g.
# "Question 1 of 106\nQuestion\n<stem>" or "Answer 1 of 106\nAnswer\nSolution\n<text>".
# The lookbehind restricts this to right after a header's number so it can't
# match "of <n>" occurring naturally elsewhere in question text.
QUESTION_OF_TOTAL_NOISE_PATTERN = re.compile(
    r"(?<=\d)\s+of\s+\d{1,4}\s*\n\s*(Question|Answer)\s*\n(\s*Solution\s*\n)?", re.IGNORECASE
)

# ---------- Answer key patterns ----------

# Style A: "1. B", "1) B", "1 - B", "1: B" all on one line
ANSWER_KEY_LINE = re.compile(r"^\s*(\d{1,3})[\.\)\-:]?\s*([ABC])\s*$", re.MULTILINE)
ANSWER_KEY_LINE_LOOSE = re.compile(r"(\d{1,3})\s*[\.\)\-:]\s*([ABC])\b")

# Style B: "Answer 1" alone on its own line. Same OCR-noise tolerance as
# QUESTION_HEADER_PATTERN above (trailing "|"/":"/"." noise is common), plus
# an optional trailing "s" ("Answers 1") -- some scans consistently misread
# the header this way for an entire session while getting it right elsewhere
# in the same document, silently zeroing out that session's answer key.
# "Answers N" is specific enough (requires a number right after) that this
# doesn't meaningfully risk matching ordinary prose.
ANSWER_HEADER_PATTERN = re.compile(r"Answers?\s*(\d{1,3})\b", re.MULTILINE)

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
    # Keep only the *first* occurrence of each letter. If a question header
    # upstream failed to match (merging two questions' text into one block),
    # this stops the second question's options from silently overwriting the
    # first question's real options.
    opts = {"A": "", "B": "", "C": ""}
    for oi, om in enumerate(option_matches):
        letter = om.group(1).upper()
        if opts[letter]:
            continue
        opt_start = om.start()
        opt_end = option_matches[oi + 1].start() if oi + 1 < len(option_matches) else len(block)
        full_opt = block[opt_start:opt_end]
        text = re.sub(r"^\(?[ABCabc]\)?[\.\)\,]\s+", "", full_opt).strip()
        opts[letter] = text
    return opts


# Some QBank-style answer keys explain *every* option rather than just
# restating the correct one, e.g. "A. Incorrect because...\nB. Incorrect
# because...\nC. Correct. ...". "Incorrect" contains "correct" as a
# substring but never at a word boundary, so \bCorrect\b safely distinguishes
# the two without extra bookkeeping.
_CORRECT_MARK = re.compile(r"\bCorrect\b", re.IGNORECASE)
_INCORRECT_MARK = re.compile(r"\bIncorrect\b", re.IGNORECASE)


def _extract_answer_from_block(block):
    """
    Finds the correct-answer letter (and, if available, an explanation) in
    one "Answer N" block. Two block styles are supported:
      - Restates only the correct option, e.g. "A. No" -- that option's
        letter is the answer, and any text after that line is captured as
        an optional explanation.
      - Explains every option, e.g. "A. Incorrect because...\nB. Incorrect
        because...\nC. Correct. ..." -- the option explicitly marked
        "Correct" (not "Incorrect") is the answer, and the whole "A/B/C"
        run it belongs to becomes the explanation, so the reasoning for
        every choice -- not just the right one -- is visible on review.

    Some providers restate the plain options *before* the Correct/Incorrect
    explanations in the same block (i.e. two separate A/B/C runs). Each new
    "A" match starts a fresh run, so the explanation is sliced from the run
    that actually contains the Correct/Incorrect verdict, not from
    whichever "A" happens to appear first in the block.

    Returns (letter, explanation), or (None, "") if no option line is found.
    """
    option_matches = list(OPTION_PATTERN.finditer(block))
    if not option_matches:
        return None, ""

    run_start = 0
    for oi, om in enumerate(option_matches):
        if om.group(1).upper() == "A":
            run_start = oi
        opt_start = om.start()
        opt_end = option_matches[oi + 1].start() if oi + 1 < len(option_matches) else len(block)
        opt_text = block[opt_start:opt_end]
        if _INCORRECT_MARK.search(opt_text):
            continue
        if _CORRECT_MARK.search(opt_text):
            return om.group(1).upper(), block[option_matches[run_start].start():].strip()

    # No option explicitly marked Correct/Incorrect -- assume the single
    # restated line found is the correct option (the common CFA-mock style).
    first = option_matches[0]
    line_end = block.find("\n", first.end())
    explanation = block[line_end:].strip() if line_end != -1 else ""
    return first.group(1).upper(), explanation


def _answers_from_header_pattern(raw_text, header_pattern):
    """Runs _extract_answer_from_block over every block delimited by
    header_pattern, returning {q_number: (letter, explanation)}."""
    header_matches = list(header_pattern.finditer(raw_text))
    if len(header_matches) < 3:
        return {}
    results = {}
    for idx, m in enumerate(header_matches):
        q_num = int(m.group(1))
        start = m.end()
        end = header_matches[idx + 1].start() if idx + 1 < len(header_matches) else len(raw_text)
        letter, explanation = _extract_answer_from_block(raw_text[start:end])
        if letter:
            results[q_num] = (letter, explanation)
    return results


def parse_answer_key(raw_text: str):
    """
    Returns a dict {q_number: 'A'/'B'/'C'} parsed from an answer-key style text
    (either a standalone answer key PDF, or a section of a combined mock PDF).

    Tries "Answer N" header style first. Some providers instead restate
    "Question N" as the delimiter inside a standalone answer-key PDF (the
    question paper and the answer key both use "Question N", just in
    different files), so that's tried next. Finally falls back to inline
    "N. B" style.
    """
    for pattern in (ANSWER_HEADER_PATTERN, QUESTION_HEADER_PATTERN):
        found = _answers_from_header_pattern(raw_text, pattern)
        if found:
            return {q: letter for q, (letter, _) in found.items()}

    answers = {}
    for m in ANSWER_KEY_LINE.finditer(raw_text):
        answers[int(m.group(1))] = m.group(2)
    if len(answers) < 5:  # fall back to a looser pattern if strict one found almost nothing
        for m in ANSWER_KEY_LINE_LOOSE.finditer(raw_text):
            q = int(m.group(1))
            answers.setdefault(q, m.group(2))
    return answers


def parse_answer_key_with_explanations(raw_text: str):
    """
    Like parse_answer_key, but also captures a rationale/explanation for
    each question (see _extract_answer_from_block for the two block styles
    this handles, and parse_answer_key for the header styles tried).

    Returns {q_number: {"correct_answer": "A"/"B"/"C", "explanation": str}}.
    Only the "Answer N" / "Question N" header styles carry explanations in
    practice -- the inline "N. B" fallback style has no room for rationale
    text, so it always comes back with an empty explanation.
    """
    for pattern in (ANSWER_HEADER_PATTERN, QUESTION_HEADER_PATTERN):
        found = _answers_from_header_pattern(raw_text, pattern)
        if found:
            return {q: {"correct_answer": letter, "explanation": explanation}
                     for q, (letter, explanation) in found.items()}

    # Fallback inline styles ("1. B") never carry rationale text.
    return {q: {"correct_answer": letter, "explanation": ""} for q, letter in parse_answer_key(raw_text).items()}


def merge_answer_key_with_explanations(questions, answer_map):
    for q in questions:
        info = answer_map.get(q["q_number"])
        q["correct_answer"] = info.get("correct_answer") if info else None
        q["explanation"] = info.get("explanation", "") if info else ""
    return questions


def find_embedded_answer_key(raw_text: str) -> str:
    """
    Given the full text of a single-section PDF (questions + an answer key
    in the same file, no "Session N" markers to split on), returns just the
    answer-key portion.

    Locates the first "Answer N" header and takes everything from there
    onward. This matters because providers that include a rationale
    paragraph per answer (QBank-style) can have an answer-key section far
    larger than the question section -- a fixed "last N% of the document"
    guess badly undershoots and misses most answers in that case. Falls back
    to the last 30% of the text if no "Answer N" header style is present
    (e.g. an inline "1. B" style key, which has no clear section marker).
    """
    header_matches = list(ANSWER_HEADER_PATTERN.finditer(raw_text))
    if len(header_matches) >= 3:
        return raw_text[header_matches[0].start():]
    return raw_text[int(len(raw_text) * 0.7):]


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


def strip_header_noise(text: str) -> str:
    """Removes repeated running-header/footer text that OCR sometimes injects
    mid-question or mid-option (e.g. 'Mock Exam 1 Session 1 - Questions'),
    and "N of <total>" + redundant label-line boilerplate some QBank
    providers repeat right after every "Question N"/"Answer N" header."""
    text = HEADER_NOISE_PATTERN.sub(" ", text)
    text = QUESTION_OF_TOTAL_NOISE_PATTERN.sub(" ", text)
    return text


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
        q_text = strip_header_noise(parts.get("questions_text", ""))
        a_text = strip_header_noise(parts.get("answers_text", ""))
        questions = parse_questions(q_text)
        answer_map = parse_answer_key(a_text) if a_text else {}
        questions = merge_answer_key(questions, answer_map)
        result[sess] = questions
    return result
