from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from flask import Flask, jsonify, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "itil_questions_store.db"
STATS_DB_PATH = BASE_DIR / "exam_stats.db"
TOTAL_QUESTIONS = 203
QUIZ_SIZE = 40
ANSWER_MARKERS = ("\u6b63\u786e\u7b54\u6848", "\u7b54\u6848")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "12"))
AI_PREFETCH_WORKERS = max(1, int(os.getenv("AI_PREFETCH_WORKERS", "4")))
EXAM_CACHE_TTL_SECONDS = int(os.getenv("EXAM_CACHE_TTL_SECONDS", "7200"))
AI_EXPLANATION_PLACEHOLDER = "AI解读生成中，请稍候..."

OBJECT_PATTERN = re.compile(rb"(?<!\d)(\d+)\s+0\s+obj\b(.*?)\bendobj", re.S)
STREAM_PATTERN = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
FONT_TOKEN_PATTERN = re.compile(
    r"/(\w+)\s+[\d.\-]+\s+Tf|<([0-9A-Fa-f]+)>\s*Tj|\[(.*?)\]\s*TJ", re.S
)

app = Flask(__name__)
AI_EXECUTOR = ThreadPoolExecutor(max_workers=AI_PREFETCH_WORKERS)
EXAM_CACHE: dict[str, dict[str, Any]] = {}
EXAM_CACHE_LOCK = threading.Lock()

SORT_FIELD_MAP = {
    "question": "question_number",
    "correct": "correct_count",
    "wrong": "wrong_count",
    "unanswered": "unanswered_count",
}


def _fallback_explanation(item: dict[str, Any], user_answer: str | None = None) -> str:
    answer = str(item.get("correct_answer", ""))
    answer_text = str(item.get("options", {}).get(answer, ""))
    user_answer = (user_answer or "").strip().upper()

    if user_answer in {"A", "B", "C", "D"} and user_answer != answer:
        wrong_text = str(item.get("options", {}).get(user_answer, ""))
        return (
            f"你选了 {user_answer}（{wrong_text}），但它不符合题干重点。"
            f"应选 {answer}（{answer_text}），先抓题干关键词再对照选项。"
        )

    if answer_text:
        return f"本题应选 {answer}（{answer_text}），它与题干条件最匹配。"
    return f"本题应选 {answer}，它与题干条件最匹配。"


def _cleanup_exam_cache() -> None:
    now = time.time()
    expired_ids: list[str] = []
    with EXAM_CACHE_LOCK:
        for exam_id, exam in EXAM_CACHE.items():
            created_at = float(exam.get("created_at", now))
            if now - created_at > EXAM_CACHE_TTL_SECONDS:
                expired_ids.append(exam_id)
        for exam_id in expired_ids:
            EXAM_CACHE.pop(exam_id, None)


def _build_question_payload(records: Iterable[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in records:
        payload.append(
            {
                "question_id": int(row["id"]),
                "question_number": int(row["question_number"]),
                "question_text": str(row["question_text"]),
                "options": {
                    "A": str(row["option_a"]),
                    "B": str(row["option_b"]),
                    "C": str(row["option_c"]),
                    "D": str(row["option_d"]),
                },
                "correct_answer": str(row["correct_answer"]),
            }
        )
    return payload


def _register_exam(question_payload: list[dict[str, Any]]) -> str:
    exam_id = uuid.uuid4().hex
    questions = [dict(item) for item in question_payload]
    question_numbers = [int(item["question_number"]) for item in questions]
    with EXAM_CACHE_LOCK:
        EXAM_CACHE[exam_id] = {
            "created_at": time.time(),
            "updated_at": time.time(),
            "prefetch_started": False,
            "questions": questions,
            "question_numbers": question_numbers,
            "questions_by_number": {
                int(item["question_number"]): item for item in questions
            },
            "pending_numbers": set(question_numbers),
            "generation_by_number": {number: 0 for number in question_numbers},
            "explanations": {},
        }
    return exam_id


def _exam_exists(exam_id: str) -> bool:
    with EXAM_CACHE_LOCK:
        return exam_id in EXAM_CACHE


def _request_single_ai_explanation(
    question: dict[str, Any], user_answer: str | None = None
) -> str:
    if not DEEPSEEK_API_KEY:
        return _fallback_explanation(question, user_answer)

    options = question["options"]
    option_text = "\n".join(
        [
            f"A. {options['A']}",
            f"B. {options['B']}",
            f"C. {options['C']}",
            f"D. {options['D']}",
        ]
    )
    user_answer = (user_answer or "").strip().upper()
    correct_answer = str(question["correct_answer"])
    correct_text = str(options.get(correct_answer, ""))
    selected_text = str(options.get(user_answer, "")) if user_answer else ""

    answer_context = f"正确答案：{correct_answer}（{correct_text}）\n"
    if user_answer in {"A", "B", "C", "D"}:
        answer_context += f"用户作答：{user_answer}（{selected_text}）\n"
        if user_answer != correct_answer:
            answer_context += (
                "用户答错了。请重点解释：为什么这个错选项容易误选、它错在哪里、"
                "应该怎么一步步排除并选到正确项。"
            )
        else:
            answer_context += "用户答对了。请重点解释为何该选项成立。"
    else:
        answer_context += "用户未作答。请只解释正确选项为何成立。"

    user_prompt = (
        "请用白话解释这道 ITIL 4 Foundation 单选题。\n"
        f"题目：{question['question_text']}\n"
        f"选项：\n{option_text}\n"
        f"{answer_context}\n\n"
        "要求：\n"
        "1) 用通俗白话，字数在35-100字之间；\n"
        "2) 先说题干考点，再解释选项逻辑；\n"
        "3) 答错时必须说明“为什么会选错、错在哪、应该怎么选”；\n"
        "4) 只输出正文，不要标题、序号、Markdown。"
    )
    payload = {
        "model": DEEPSEEK_MODEL,
        "temperature": 0.25,
        "max_tokens": 320,
        "messages": [
            {
                "role": "system",
                "content": "你是 ITIL 4 Foundation 讲师。解释要准确、口语化、让新手能立刻理解。",
            },
            {"role": "user", "content": user_prompt},
        ],
    }
    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    endpoint = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    http_request = urllib_request.Request(
        endpoint,
        data=request_data,
        method="POST",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib_request.urlopen(http_request, timeout=DEEPSEEK_TIMEOUT_SECONDS) as response:
        response_text = response.read().decode("utf-8", errors="replace")

    response_json = json.loads(response_text)
    content = (
        response_json.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    code_block = re.search(r"```(?:\w+)?\s*(.*?)```", content, re.S)
    if code_block:
        content = code_block.group(1)

    cleaned = re.sub(r"\s+", " ", content).strip()
    if not cleaned:
        raise ValueError("Empty AI explanation content.")
    return cleaned


def _prefetch_single_explanation(
    exam_id: str,
    question_number: int,
    generation: int,
    use_user_answer: bool,
) -> None:
    with EXAM_CACHE_LOCK:
        exam = EXAM_CACHE.get(exam_id)
        if not exam:
            return
        question = exam.get("questions_by_number", {}).get(question_number)
        if not question:
            return
        user_answer = str(question.get("user_answer", "")).strip().upper() if use_user_answer else ""

    try:
        explanation = _request_single_ai_explanation(question, user_answer=user_answer)
    except (urllib_error.URLError, urllib_error.HTTPError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"[AI] explanation failed for Q{question_number}: {exc}")
        explanation = _fallback_explanation(question, user_answer=user_answer)

    with EXAM_CACHE_LOCK:
        exam = EXAM_CACHE.get(exam_id)
        if not exam:
            return
        current_generation = int(exam.get("generation_by_number", {}).get(question_number, 0))
        if generation != current_generation:
            return
        exam["explanations"][question_number] = explanation
        exam["pending_numbers"].discard(question_number)
        exam["updated_at"] = time.time()


def _start_exam_prefetch(exam_id: str) -> None:
    with EXAM_CACHE_LOCK:
        exam = EXAM_CACHE.get(exam_id)
        if not exam or exam.get("prefetch_started"):
            return
        exam["prefetch_started"] = True
        question_numbers = list(exam.get("question_numbers", []))
        generation_map = dict(exam.get("generation_by_number", {}))

    for question_number in question_numbers:
        generation = int(generation_map.get(question_number, 0))
        AI_EXECUTOR.submit(
            _prefetch_single_explanation,
            exam_id,
            int(question_number),
            generation,
            False,
        )


def _get_exam_progress(exam_id: str) -> dict[str, Any] | None:
    with EXAM_CACHE_LOCK:
        exam = EXAM_CACHE.get(exam_id)
        if not exam:
            return None

        explanations = {
            str(int(number)): text
            for number, text in exam.get("explanations", {}).items()
        }
        total = len(exam.get("question_numbers", []))
        done_count = len(explanations)
        return {
            "exam_id": exam_id,
            "done_count": done_count,
            "total": total,
            "is_done": done_count >= total and total > 0,
            "explanations": explanations,
            "updated_at": exam.get("updated_at"),
        }


def _refresh_wrong_answer_tasks(exam_id: str, results: list[dict[str, Any]]) -> None:
    review_tasks: list[tuple[int, int]] = []
    with EXAM_CACHE_LOCK:
        exam = EXAM_CACHE.get(exam_id)
        if not exam:
            return

        by_number = exam.get("questions_by_number", {})
        generation_map = exam.get("generation_by_number", {})
        for item in results:
            question_number = int(item["question_number"])
            user_answer = str(item.get("user_answer", "")).strip().upper()
            correct_answer = str(item.get("correct_answer", "")).strip().upper()

            question = by_number.get(question_number)
            if question is None:
                continue
            question["user_answer"] = user_answer

            if user_answer in {"A", "B", "C", "D"} and user_answer != correct_answer:
                next_generation = int(generation_map.get(question_number, 0)) + 1
                generation_map[question_number] = next_generation
                exam["pending_numbers"].add(question_number)
                exam["explanations"].pop(question_number, None)
                review_tasks.append((question_number, next_generation))

        exam["updated_at"] = time.time()

    for question_number, generation in review_tasks:
        AI_EXECUTOR.submit(
            _prefetch_single_explanation,
            exam_id,
            question_number,
            generation,
            True,
        )


def open_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    return connection


def open_stats_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(STATS_DB_PATH)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    return connection


def create_stats_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS question_stats (
            question_id INTEGER PRIMARY KEY,
            question_number INTEGER UNIQUE NOT NULL,
            correct_count INTEGER NOT NULL DEFAULT 0,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            unanswered_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )


def sync_stats_questions() -> None:
    with get_connection() as questions_connection:
        question_rows = questions_connection.execute(
            "SELECT id, question_number FROM questions ORDER BY question_number"
        ).fetchall()

    if not question_rows:
        return

    payload = [(int(row["id"]), int(row["question_number"])) for row in question_rows]
    question_ids = [item[0] for item in payload]
    now = time.time()
    with open_stats_connection() as stats_connection:
        create_stats_tables(stats_connection)
        stats_connection.executemany(
            """
            INSERT INTO question_stats (question_id, question_number, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                question_number = excluded.question_number
            """,
            [(question_id, question_number, now) for question_id, question_number in payload],
        )

        placeholders = ",".join("?" for _ in question_ids)
        stats_connection.execute(
            f"DELETE FROM question_stats WHERE question_id NOT IN ({placeholders})",
            question_ids,
        )


def record_exam_stats(results: list[dict[str, Any]]) -> None:
    if not results:
        return

    sync_stats_questions()
    now = time.time()

    with open_stats_connection() as stats_connection:
        create_stats_tables(stats_connection)
        for item in results:
            question_id = int(item["question_id"])
            question_number = int(item["question_number"])
            user_answer = str(item.get("user_answer", "")).strip().upper()
            correct_answer = str(item.get("correct_answer", "")).strip().upper()

            if user_answer in {"A", "B", "C", "D"}:
                bucket = "correct_count" if user_answer == correct_answer else "wrong_count"
            else:
                bucket = "unanswered_count"

            stats_connection.execute(
                f"""
                INSERT INTO question_stats (question_id, question_number, {bucket}, updated_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(question_id) DO UPDATE SET
                    question_number = excluded.question_number,
                    {bucket} = {bucket} + 1,
                    updated_at = excluded.updated_at
                """,
                (question_id, question_number, now),
            )


def query_stats_rows(sort_key: str, order: str) -> tuple[list[dict[str, Any]], str, str]:
    normalized_sort = sort_key if sort_key in SORT_FIELD_MAP else "question"
    normalized_order = order.lower()
    if normalized_order not in {"asc", "desc"}:
        normalized_order = "asc" if normalized_sort == "question" else "desc"

    sort_column = SORT_FIELD_MAP[normalized_sort]
    sql_order = "ASC" if normalized_order == "asc" else "DESC"
    tie_breaker = "ASC" if sort_column != "question_number" else sql_order

    with open_stats_connection() as stats_connection:
        stats_connection.row_factory = sqlite3.Row
        create_stats_tables(stats_connection)
        stat_rows = stats_connection.execute(
            f"""
            SELECT question_id, question_number, correct_count, wrong_count, unanswered_count
            FROM question_stats
            ORDER BY {sort_column} {sql_order}, question_number {tie_breaker}
            """
        ).fetchall()

    with get_connection() as questions_connection:
        text_rows = questions_connection.execute(
            "SELECT id, question_text FROM questions"
        ).fetchall()
    question_text_by_id = {int(row["id"]): row["question_text"] for row in text_rows}

    rows: list[dict[str, Any]] = []
    for row in stat_rows:
        rows.append(
            {
                "question_id": int(row["question_id"]),
                "question_number": int(row["question_number"]),
                "question_text": question_text_by_id.get(int(row["question_id"]), ""),
                "correct_count": int(row["correct_count"]),
                "wrong_count": int(row["wrong_count"]),
                "unanswered_count": int(row["unanswered_count"]),
            }
        )

    return rows, normalized_sort, normalized_order


def find_pdf_path() -> Path:
    pdf_files = sorted(BASE_DIR.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError("PDF file not found in project directory.")

    for pdf_path in pdf_files:
        if "ITIL" in pdf_path.name.upper():
            return pdf_path
    return pdf_files[0]


def get_stream_data(object_body: bytes) -> bytes | None:
    match = STREAM_PATTERN.search(object_body)
    if not match:
        return None

    stream_data = match.group(1)
    dictionary_part = object_body[: match.start()]
    if b"/FlateDecode" in dictionary_part:
        stream_data = zlib.decompress(stream_data)
    return stream_data


def hex_to_unicode(hex_string: str) -> str:
    raw = bytes.fromhex(hex_string)
    if len(raw) % 2 != 0:
        raw = b"\x00" + raw
    return raw.decode("utf-16-be", errors="ignore")


def parse_cmap(cmap_stream: bytes) -> dict[int, str]:
    text = cmap_stream.decode("latin1", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    mapping: dict[int, str] = {}

    index = 0
    while index < len(lines):
        line = lines[index]

        match = re.match(r"(\d+)\s+beginbfchar", line)
        if match:
            count = int(match.group(1))
            for row in lines[index + 1 : index + 1 + count]:
                pair = re.match(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", row)
                if pair:
                    mapping[int(pair.group(1), 16)] = hex_to_unicode(pair.group(2))
            index += count + 1
            continue

        match = re.match(r"(\d+)\s+beginbfrange", line)
        if match:
            count = int(match.group(1))
            for row in lines[index + 1 : index + 1 + count]:
                range_match = re.match(
                    r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", row
                )
                if range_match:
                    start = int(range_match.group(1), 16)
                    end = int(range_match.group(2), 16)
                    destination = int(range_match.group(3), 16)
                    for code in range(start, end + 1):
                        mapping[code] = hex_to_unicode(
                            f"{destination + (code - start):04X}"
                        )
                    continue

                array_match = re.match(
                    r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+\[(.*)\]", row
                )
                if array_match:
                    start = int(array_match.group(1), 16)
                    destinations = re.findall(r"<([0-9A-Fa-f]+)>", array_match.group(3))
                    for offset, destination in enumerate(destinations):
                        mapping[start + offset] = hex_to_unicode(destination)
            index += count + 1
            continue

        index += 1

    return mapping


def decode_hex_text(hex_string: str, cmap: dict[int, str]) -> str:
    raw = bytes.fromhex(hex_string)
    decoded: list[str] = []
    for i in range(0, len(raw), 2):
        code = (raw[i] << 8) | raw[i + 1]
        decoded.append(cmap.get(code, chr(code)))
    return "".join(decoded)


def extract_text_lines_from_pdf(pdf_path: Path) -> list[str]:
    pdf_bytes = pdf_path.read_bytes()
    objects = {
        int(match.group(1)): match.group(2)
        for match in OBJECT_PATTERN.finditer(pdf_bytes)
    }

    font_cmaps: dict[int, dict[int, str]] = {}
    for object_id, object_body in objects.items():
        if b"/Type /Font" not in object_body or b"/ToUnicode" not in object_body:
            continue
        to_unicode_match = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", object_body)
        if not to_unicode_match:
            continue
        cmap_object_id = int(to_unicode_match.group(1))
        cmap_stream = get_stream_data(objects[cmap_object_id])
        if cmap_stream is not None:
            font_cmaps[object_id] = parse_cmap(cmap_stream)

    kids_match = re.search(rb"/Kids\s*\[(.*?)\]", objects[2], re.S)
    if not kids_match:
        raise ValueError("Cannot locate PDF page list.")
    page_object_ids = [
        int(value) for value in re.findall(rb"(\d+)\s+0\s+R", kids_match.group(1))
    ]

    lines: list[str] = []
    for page_id in page_object_ids:
        page_object = objects.get(page_id, b"")
        if b"/Type /Page" not in page_object:
            continue

        page_fonts: dict[str, dict[int, str]] = {}
        font_match = re.search(rb"/Font\s*<<(.+?)>>", page_object, re.S)
        if font_match:
            for font_name, font_id in re.findall(
                rb"/(\w+)\s+(\d+)\s+0\s+R", font_match.group(1)
            ):
                page_fonts[font_name.decode()] = font_cmaps.get(int(font_id), {})

        content_match = re.search(rb"/Contents\s*(\d+)\s+0\s+R", page_object)
        if not content_match:
            continue
        content_object_id = int(content_match.group(1))
        content_stream = get_stream_data(objects[content_object_id])
        if content_stream is None:
            continue

        stream_text = content_stream.decode("latin1", errors="ignore")
        current_font: str | None = None
        for text_block in re.findall(r"BT(.*?)ET", stream_text, re.S):
            font_in_block = current_font
            fragments: list[str] = []
            for token in FONT_TOKEN_PATTERN.finditer(text_block):
                if token.group(1):
                    font_in_block = token.group(1)
                    continue

                cmap = page_fonts.get(font_in_block or "", {})
                if token.group(2):
                    fragments.append(decode_hex_text(token.group(2), cmap))
                    continue

                for hex_piece in re.findall(r"<([0-9A-Fa-f]+)>", token.group(3)):
                    fragments.append(decode_hex_text(hex_piece, cmap))

            current_font = font_in_block
            line = "".join(fragments).strip()
            if line:
                lines.append(line)

    return lines


def normalize_number_lines(lines: Iterable[str]) -> list[str]:
    source = [line.strip() for line in lines if line.strip()]
    normalized: list[str] = []
    index = 0

    while index < len(source):
        current = source[index]
        next_line = source[index + 1] if index + 1 < len(source) else ""

        if re.fullmatch(r"\d{1,3}", current) and re.fullmatch(r"\d{1,3}\.", next_line):
            normalized.append(current + next_line)
            index += 2
            continue

        if re.fullmatch(r"\d{1,3}", current) and next_line == ".":
            normalized.append(current + ".")
            index += 2
            continue

        normalized.append(current)
        index += 1

    return normalized


def smart_join(parts: Iterable[str]) -> str:
    result = ""
    for part in parts:
        fragment = part.strip()
        if not fragment:
            continue
        if (
            result
            and result[-1].isascii()
            and fragment[0].isascii()
            and result[-1].isalnum()
            and fragment[0].isalnum()
        ):
            result += " "
        result += fragment
    return result


def parse_question_block(question_number: int, block: list[str]) -> dict[str, str]:
    stem_parts: list[str] = []
    options = {"A": [], "B": [], "C": [], "D": []}
    current_section = "stem"
    answer = ""

    index = 0
    while index < len(block):
        line = block[index].strip()
        if not line:
            index += 1
            continue

        if re.fullmatch(r"[ABCD]\.", line):
            current_section = line[0]
            index += 1
            continue

        marker_index = -1
        marker_text = ""
        for marker in ANSWER_MARKERS:
            if marker in line:
                marker_index = line.index(marker)
                marker_text = marker
                break

        if marker_index != -1:
            left_side = line[:marker_index].strip()
            if left_side and current_section in options:
                options[current_section].append(left_side)

            answer_part = line[marker_index + len(marker_text) :]
            inline_answer = re.search(r"([ABCD])", answer_part)
            if inline_answer:
                answer = inline_answer.group(1)
            else:
                cursor = index + 1
                while cursor < len(block) and not block[cursor].strip():
                    cursor += 1
                if cursor < len(block) and re.fullmatch(r"[ABCD]", block[cursor].strip()):
                    answer = block[cursor].strip()
                    index = cursor

            current_section = "answer"
            index += 1
            continue

        if current_section == "stem":
            stem_parts.append(line)
        elif current_section in options:
            options[current_section].append(line)

        index += 1

    parsed_question = {
        "question_number": str(question_number),
        "question_text": smart_join(stem_parts),
        "option_a": smart_join(options["A"]),
        "option_b": smart_join(options["B"]),
        "option_c": smart_join(options["C"]),
        "option_d": smart_join(options["D"]),
        "correct_answer": answer,
    }
    return parsed_question


def parse_questions_from_lines(lines: list[str]) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    position = 0

    for question_number in range(1, TOTAL_QUESTIONS + 1):
        marker = f"{question_number}."
        start = None
        for idx in range(position, len(lines)):
            if lines[idx] == marker:
                start = idx
                break

        if start is None:
            raise ValueError(f"Question {question_number} not found.")

        if question_number < TOTAL_QUESTIONS:
            next_marker = f"{question_number + 1}."
            end = len(lines)
            for idx in range(start + 1, len(lines)):
                if lines[idx] == next_marker:
                    end = idx
                    break
        else:
            end = len(lines)

        block = lines[start + 1 : end]
        question = parse_question_block(question_number, block)
        required_fields = (
            question["question_text"],
            question["option_a"],
            question["option_b"],
            question["option_c"],
            question["option_d"],
            question["correct_answer"],
        )
        if not all(required_fields):
            raise ValueError(f"Question {question_number} parsing incomplete.")

        questions.append(question)
        position = end

    return questions


def create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_number INTEGER UNIQUE NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_answer TEXT NOT NULL CHECK (correct_answer IN ('A', 'B', 'C', 'D'))
        )
        """
    )


def build_question_bank(force_rebuild: bool = False) -> None:
    # 一次性初始化工具：从 PDF 重新提取并写入 SQLite。
    # 题库已经建好时，Web 运行阶段不需要调用此方法。
    with open_db_connection() as connection:
        create_tables(connection)
        current_count = connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

    if current_count == TOTAL_QUESTIONS and not force_rebuild:
        return

    pdf_path = find_pdf_path()
    raw_lines = extract_text_lines_from_pdf(pdf_path)
    normalized_lines = normalize_number_lines(raw_lines)
    questions = parse_questions_from_lines(normalized_lines)

    with open_db_connection() as connection:
        create_tables(connection)
        connection.execute("DELETE FROM questions")
        connection.executemany(
            """
            INSERT INTO questions (
                question_number,
                question_text,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    int(question["question_number"]),
                    question["question_text"],
                    question["option_a"],
                    question["option_b"],
                    question["option_c"],
                    question["option_d"],
                    question["correct_answer"],
                )
                for question in questions
            ],
        )


def get_connection() -> sqlite3.Connection:
    connection = open_db_connection()
    connection.row_factory = sqlite3.Row
    return connection


@app.route("/", methods=["GET"])
def quiz_page():
    # 数据库已完成初始化，运行期不再自动执行 PDF 提取与重建。
    # 如需重建，请手动调用 build_question_bank(force_rebuild=True)。
    # build_question_bank(force_rebuild=False)
    with get_connection() as connection:
        questions = connection.execute(
            """
            SELECT id, question_number, question_text, option_a, option_b, option_c, option_d, correct_answer
            FROM questions
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (QUIZ_SIZE,),
        ).fetchall()

    if not questions:
        return "Question bank is empty. Please initialize the database first.", 500

    sync_stats_questions()
    _cleanup_exam_cache()
    exam_id = _register_exam(_build_question_payload(questions))
    _start_exam_prefetch(exam_id)
    return render_template("quiz.html", questions=questions, exam_id=exam_id)


@app.route("/submit", methods=["POST"])
def submit_quiz():
    exam_id = request.form.get("exam_id", "").strip()
    question_ids = [
        int(value) for value in request.form.getlist("question_id") if value.isdigit()
    ]
    if not question_ids:
        return redirect(url_for("quiz_page"))

    placeholders = ",".join("?" for _ in question_ids)
    query = f"""
        SELECT id, question_number, question_text, option_a, option_b, option_c, option_d, correct_answer
        FROM questions
        WHERE id IN ({placeholders})
    """

    with get_connection() as connection:
        fetched = connection.execute(query, question_ids).fetchall()

    question_map = {row["id"]: row for row in fetched}
    ordered_rows = [question_map[qid] for qid in question_ids if qid in question_map]
    question_payload = _build_question_payload(ordered_rows)

    if not exam_id or not _exam_exists(exam_id):
        _cleanup_exam_cache()
        exam_id = _register_exam(question_payload)
    _start_exam_prefetch(exam_id)

    results = []
    score = 0
    for row in ordered_rows:
        user_answer = request.form.get(f"answer_{row['id']}", "")
        correct_answer = row["correct_answer"]
        is_correct = user_answer == correct_answer
        if is_correct:
            score += 1

        results.append(
            {
                "question_id": int(row["id"]),
                "question_number": row["question_number"],
                "question_text": row["question_text"],
                "options": {
                    "A": row["option_a"],
                    "B": row["option_b"],
                    "C": row["option_c"],
                    "D": row["option_d"],
                },
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
            }
        )

    record_exam_stats(results)
    _refresh_wrong_answer_tasks(exam_id, results)

    progress = _get_exam_progress(exam_id)
    explanation_map = progress["explanations"] if progress else {}
    for item in results:
        explanation = explanation_map.get(str(int(item["question_number"])))
        item["ai_explanation"] = explanation if explanation else AI_EXPLANATION_PLACEHOLDER

    ai_done_count = progress["done_count"] if progress else 0
    ai_total_count = progress["total"] if progress else len(results)
    return render_template(
        "result.html",
        results=results,
        score=score,
        total=len(results),
        exam_id=exam_id,
        ai_done_count=ai_done_count,
        ai_total_count=ai_total_count,
        ai_placeholder=AI_EXPLANATION_PLACEHOLDER,
    )


@app.route("/stats", methods=["GET"])
def stats_page():
    sync_stats_questions()
    sort_key = request.args.get("sort", "question")
    order = request.args.get("order", "asc")
    rows, normalized_sort, normalized_order = query_stats_rows(sort_key, order)

    next_orders: dict[str, str] = {}
    for key in SORT_FIELD_MAP:
        if key == normalized_sort:
            next_orders[key] = "desc" if normalized_order == "asc" else "asc"
        else:
            next_orders[key] = "asc" if key == "question" else "desc"

    return render_template(
        "stats.html",
        stats_rows=rows,
        total_questions=len(rows),
        sort_key=normalized_sort,
        sort_order=normalized_order,
        next_orders=next_orders,
    )


@app.route("/api/exam/<exam_id>/ai-status", methods=["GET"])
def exam_ai_status(exam_id: str):
    progress = _get_exam_progress(exam_id)
    if progress is None:
        return jsonify({"error": "exam_not_found"}), 404
    return jsonify(progress)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ITIL 4 Foundation mock exam app")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=5000, help="Server port")
    # 数据库已准备完毕，默认运行不提供重建参数。
    # 如需重建可恢复以下参数并在入口处调用 build_question_bank。
    # parser.add_argument(
    #     "--rebuild-db",
    #     action="store_true",
    #     help="Force rebuilding the SQLite question bank",
    # )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    # 运行阶段不再自动重建数据库（避免每次启动读取 PDF）。
    # build_question_bank(force_rebuild=args.rebuild_db)
    app.run(host=args.host, port=args.port, debug=True)
