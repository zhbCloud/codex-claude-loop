from __future__ import annotations

import re
from pathlib import Path

from .common import DelegateError, STRICT_REQUIRED_HEADINGS
from .contract import load_contract
from .io_utils import read_text


def normalize_heading(value: str) -> str:
    value = value.strip().strip("#").strip().rstrip(":").strip().lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value).strip()


def heading_aliases() -> dict[str, str]:
    task_file = load_contract().get("taskFile", {})
    required = list(task_file.get("requiredSections") or [])
    aliases = task_file.get("sectionAliases") if isinstance(task_file.get("sectionAliases"), dict) else {}
    mapping: dict[str, str] = {}
    for section in required:
        candidates = aliases.get(section) if isinstance(aliases.get(section), list) else [section]
        for candidate in candidates:
            mapping[normalize_heading(str(candidate))] = str(section)
    return mapping


def present_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith(("-", "*", ">")) or len(clean) > 100:
            continue
        headings.add(normalize_heading(clean))
    return headings


def task_file_sections(text: str) -> dict[str, str]:
    aliases = heading_aliases()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        clean = line.strip()
        normalized = normalize_heading(clean)
        if current != "Report Requirements" and clean and not clean.startswith(("-", "*", ">")) and len(clean) <= 100 and normalized in aliases:
            current = aliases[normalized]
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def has_task_contract(text: str) -> bool:
    task_file = load_contract().get("taskFile", {})
    required = list(task_file.get("requiredSections") or [])
    present = present_headings(text)
    aliases = heading_aliases()
    reverse: dict[str, set[str]] = {}
    for alias, section in aliases.items():
        reverse.setdefault(section, set()).add(alias)
    return bool(required) and all(present.intersection(reverse.get(str(section), set())) for section in required)


def placeholder_matches(text: str) -> list[str]:
    pattern = re.compile(r"\b(?:TBD|TODO|FIXME|FILL\s+IN|PLACEHOLDER)\b|待定|稍后补充", re.IGNORECASE)
    return sorted({match.group(0) for match in pattern.finditer(text)})


def missing_report_headings(text: str) -> list[str]:
    normalized = normalize_heading(text)
    return [heading for heading in STRICT_REQUIRED_HEADINGS if normalize_heading(heading) not in normalized]


def validate_task_text(text: str, tests: list[str] | None = None) -> None:
    task_file = load_contract().get("taskFile", {})
    required = list(task_file.get("requiredSections") or [])
    if not required:
        raise DelegateError("Task file contract is unavailable.")
    if not has_task_contract(text):
        missing = []
        present = present_headings(text)
        reverse: dict[str, set[str]] = {}
        for alias, section in heading_aliases().items():
            reverse.setdefault(section, set()).add(alias)
        for section in required:
            if not present.intersection(reverse.get(str(section), set())):
                missing.append(str(section))
        raise DelegateError("Task file contract failed. Missing required sections: " + ", ".join(missing) + ".")
    sections = task_file_sections(text)
    empty = [str(section) for section in required if not sections.get(str(section), "").strip()]
    if empty:
        raise DelegateError("Task file contract failed. Empty required sections: " + ", ".join(empty) + ".")
    placeholders = placeholder_matches(text)
    if placeholders:
        raise DelegateError("Task file contract failed. Remove placeholder text: " + ", ".join(placeholders) + ".")
    missing_report = missing_report_headings(sections.get("Report Requirements", ""))
    if missing_report:
        raise DelegateError("Task file contract failed. Report Requirements is missing headings: " + ", ".join(missing_report) + ".")
    verification_text = sections.get("Verification", "")
    missing_tests = [item for item in tests or [] if item.strip() and item.strip() not in verification_text]
    if missing_tests:
        raise DelegateError("Task file contract failed. Verification section is missing tests: " + "; ".join(missing_tests) + ".")


def validate_task_file(task_file: Path | str, tests: list[str] | None = None) -> None:
    validate_task_text(read_text(Path(task_file)), tests)
