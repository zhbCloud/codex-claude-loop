from __future__ import annotations

import re


def report_field(text: str, heading: str) -> str:
    pattern = re.compile(rf"(?im)^\s*#*\s*{re.escape(heading)}\s*:?\s*$")
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"(?m)^\s*#*\s*[A-Za-z][A-Za-z ]{2,}\s*:?\s*$", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def report_token(text: str, heading: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        normalized = re.sub(r"[^a-z0-9]+", " ", line.strip().strip("#").strip().lower()).strip()
        if normalized != heading.lower():
            continue
        for candidate in lines[index + 1 :]:
            token = candidate.strip().strip("-*` ").upper().replace(" ", "_")
            if token:
                return token
    return ""


def report_is_accepted(text: str, strict: bool) -> bool:
    final_token = report_token(text, "Final Result")
    status_token = report_token(text, "Status")
    accepted = final_token in {"PASS", "DONE"}
    if strict:
        accepted = accepted and status_token in {"PASS", "DONE"}
    return accepted
