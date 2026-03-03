#!/usr/bin/env python3
"""
ai_subject_coach.py

Purpose:
- Used by pre-push hook when the *last commit message* is invalid.
- If (and only if) the message structure/body is already correct, it asks an LLM
  to suggest a corrected *English subject line* (one line, 60–75 chars).
- It then prompts via /dev/tty (works even when the hook has no stdin) to apply:
    - y => git commit --amend (subject only, body untouched)
    - n => abort (push remains blocked)

Requirements:
- Python package: openai
- Env var: OPENAI_API_KEY
- Optional: OPENAI_MODEL (default: gpt-5-mini)
"""

import os
import re
import subprocess
import sys
import tempfile
from textwrap import dedent

SUBJECT_MIN = 60
SUBJECT_MAX = 75
LINE_MAX = 75

# You can override with: export OPENAI_MODEL="gpt-4.1-mini" (or similar)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


def sh(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def run(*args: str) -> int:
    return subprocess.call(args)


def split_message(msg: str) -> tuple[str, list[str]]:
    msg = msg.replace("\r\n", "\n").replace("\r", "\n")
    lines = msg.split("\n")
    subject = lines[0] if lines else ""
    return subject, lines


def is_structure_and_body_ok(lines: list[str]) -> tuple[bool, list[str]]:
    """
    Validates structure/body ONLY:
    - line 2 blank
    - body exists (non-empty after blank line)
    - each body line <= 75 chars
    Does NOT validate subject length (that's what we want AI to fix).
    """
    errors: list[str] = []

    # Must have blank line after subject
    if len(lines) < 2 or lines[1] != "":
        errors.append("Line 2 must be blank (required blank line after subject).")

    body_lines = lines[2:] if len(lines) >= 3 else []
    if not any(l.strip() for l in body_lines):
        errors.append("Body is required (non-empty) after the blank line.")

    for i, line in enumerate(body_lines, start=3):
        if len(line) > LINE_MAX:
            errors.append(f"Body line {i} exceeds {LINE_MAX} chars (got {len(line)}).")

    return (len(errors) == 0), errors


def apply_new_subject(new_subject: str, original_lines: list[str]) -> int:
    """
    Replace only the subject (line 1). Keep everything else intact.
    """
    amended_lines = original_lines[:]
    amended_lines[0] = new_subject

    # Preserve exact newline layout
    amended = "\n".join(amended_lines)

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
        f.write(amended)
        tmp_path = f.name

    try:
        return run("git", "commit", "--amend", "-F", tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def prompt_yes_no_via_tty(prompt: str) -> str:
    """
    Read user input from /dev/tty so it works even when hooks have no stdin.
    Returns a lowercase string (e.g. 'y', 'n', '').
    """
    try:
        with open("/dev/tty", "r") as tty_in, open("/dev/tty", "w") as tty_out:
            tty_out.write(prompt)
            tty_out.flush()
            return tty_in.readline().strip().lower()
    except Exception:
        # No TTY available (e.g., CI/non-interactive shells)
        return ""


def get_context() -> str:
    """
    Minimal context (safer): changed files + diff stats.
    Avoid sending full diffs unless you explicitly want that.
    """
    files = sh("git", "show", "--name-only", "--pretty=format:", "-1")
    stat = sh("git", "show", "--stat", "--pretty=format:", "-1")
    return f"Files changed:\n{files}\n\nDiff stat:\n{stat}"


def in_subject_range(subject: str) -> bool:
    return SUBJECT_MIN <= len(subject) <= SUBJECT_MAX and "\n" not in subject


def call_openai_subject_suggestion(current_subject: str, context: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "Python module 'openai' not found. Install it in your venv, e.g.\n"
            "  source .venv/bin/activate\n"
            "  pip install openai\n"
        ) from e

    client = OpenAI(api_key=api_key)

    system = dedent(f"""
    You are a commit-message coach. Output ONLY ONE subject line in English.
    Requirements:
    - Subject length must be {SUBJECT_MIN}-{SUBJECT_MAX} characters (inclusive).
    - Keep it specific and truthful to the context. Do NOT invent changes.
    - No trailing period. No quotes. One line only.
    """)

    user = dedent(f"""
    Current subject:
    {current_subject}

    Context:
    {context}

    Return ONLY the corrected English subject line.
    """)

    resp = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    text = resp.output_text.strip().splitlines()[0].strip()
    text = text.rstrip(".").strip()
    return text


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: ai_subject_coach.py <commit_msg_file>", file=sys.stderr)
        return 2

    msg_file = sys.argv[1]
    original_full = open(msg_file, "r", encoding="utf-8").read()
    current_subject, lines = split_message(original_full)

    # Only proceed if structure/body are already correct; we only fix subject.
    ok, structural_errors = is_structure_and_body_ok(lines)
    if not ok:
        print("❌ AI coach runs only when structure/body are already correct.")
        print("Fix these first (deterministic):")
        for e in structural_errors:
            print(f"- {e}")
        return 1

    context = get_context()

    try:
        suggestion = call_openai_subject_suggestion(current_subject, context)
    except Exception as e:
        print(f"❌ AI call failed: {e}", file=sys.stderr)
        return 1

    print("AI suggested English subject:")
    print(f"  {suggestion}")
    print(f"Length: {len(suggestion)} (required {SUBJECT_MIN}-{SUBJECT_MAX})")

    if not in_subject_range(suggestion):
        print("❌ Suggestion does not meet the subject length requirement.", file=sys.stderr)
        return 1

    ans = prompt_yes_no_via_tty("Apply this subject automatically? (y/n): ")
    if ans != "y":
        print("Not applied. Please amend manually and retry push.")
        return 1

    rc = apply_new_subject(suggestion, lines)
    if rc != 0:
        print("❌ Failed to amend commit.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())