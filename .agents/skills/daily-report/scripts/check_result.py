#!/usr/bin/env python3
"""Deterministic structure and fact guard for daily-report drafts."""
import argparse
import json
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])")
PLACEHOLDER = re.compile(r"\[(?:TODO|확인 필요|미상|추가 입력|입력 필요)[^\]]*\]", re.I)
BLOCKED_COMMAND = re.compile(r"(?:\bgit\s+push\b|\bgh\s+(?:release|pr\s+merge)\b|\brm\s+-rf\b|\bremove-item\b[^\n]*-recurse[^\n]*-force)", re.I)
PROTECTED_PATH = re.compile(r"(?:^|[/\\])(?:raw|raw_data|originals|원자료)(?:[/\\]|$)", re.I)


def check_report(payload):
    source = str(payload.get("source_text", ""))
    draft = str(payload.get("draft_text", ""))
    missing = payload.get("missing_facts", [])
    if not isinstance(missing, list):
        print("FAIL: missing_facts must be a list")
        return 1
    if not source.strip() or not draft.strip():
        print("FAIL: source_text and draft_text are required")
        return 1
    if missing:
        has_question = "?" in draft or "알려" in draft or "확인해" in draft or "질문" in draft
        if HEADING.search(draft) or not has_question:
            print("FAIL: missing facts detected but a final numbered report was drafted")
            return 1
        print("HOLD: missing facts require user clarification: " + ", ".join(map(str, missing)))
        return 2
    if PLACEHOLDER.search(draft):
        print("FAIL: unresolved placeholder found")
        return 1
    lines = draft.splitlines()
    headings = [(i, int(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    if not headings:
        print("FAIL: no numbered activity headings found")
        return 1
    expected = list(range(1, len(headings) + 1))
    actual = [number for _, number, _ in headings]
    if actual != expected or any(not title.strip() for _, _, title in headings):
        print(f"FAIL: headings must be numbered consecutively from 1; found {actual}")
        return 1
    for idx, (line_no, _, _) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_no + 1:end]).strip()
        if not body:
            print(f"FAIL: activity heading on line {line_no + 1} has no body")
            return 1
    body_text = "\n".join(line for line in lines if not HEADING.match(line))
    source_numbers = set(NUMBER.findall(source))
    draft_numbers = set(NUMBER.findall(body_text))
    added = sorted(draft_numbers - source_numbers)
    if added:
        print("FAIL: numeric facts not present in source: " + ", ".join(added))
        return 1
    print(f"PASS: {len(headings)} activities; headings, bodies, placeholders, and numeric facts checked")
    return 0


def pre_tool_use():
    try:
        event = json.load(sys.stdin)
    except Exception as exc:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": f"Could not parse hook input: {exc}"}}))
        return 0
    tool = str(event.get("tool_name", ""))
    data = event.get("tool_input", {}) or {}
    reason = None
    if tool.lower() in {"bash", "shell"}:
        command = str(data.get("command", ""))
        if BLOCKED_COMMAND.search(command):
            reason = "External publishing, merge, or destructive deletion requires explicit human approval."
    if tool.lower() in {"write", "edit", "multiedit"}:
        target = str(data.get("file_path", data.get("path", "")))
        if PROTECTED_PATH.search(target):
            reason = "Raw/original data is protected from modification. Use a read-only copy."
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", nargs="?", help="JSON file with source_text, draft_text, and missing_facts")
    parser.add_argument("--pre-tool-use", action="store_true", help="read a Claude Code PreToolUse event from stdin")
    args = parser.parse_args()
    if args.pre_tool_use:
        return pre_tool_use()
    if not args.payload:
        parser.error("payload JSON file is required unless --pre-tool-use is used")
    try:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL: cannot read payload: {exc}")
        return 1
    return check_report(payload)


if __name__ == "__main__":
    raise SystemExit(main())
