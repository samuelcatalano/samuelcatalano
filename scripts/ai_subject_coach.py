#!/usr/bin/env python3
import os
import sys
import subprocess
from textwrap import dedent

SUBJECT_MIN = 60
SUBJECT_MAX = 75

def sh(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()

def run(*args: str) -> int:
    return subprocess.call(args)

def split_message(msg: str) -> tuple[str, str]:
    msg = msg.replace("\r\n", "\n").replace("\r", "\n")
    lines = msg.split("\n")
    subject = lines[0] if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    return subject, body

def apply_new_subject(new_subject: str, original_full: str) -> int:
    # Replace only line 1, keep everything else exactly
    _, rest = split_message(original_full)
    amended = new_subject + "\n" + rest  # rest already includes the newline(s) after subject
    # Write to temp file and amend using -F
    import tempfile
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

def call_openai_subject_suggestion(current_subject: str, context: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    from openai import OpenAI
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
        model="gpt-5.2-mini",
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = resp.output_text.strip().splitlines()[0].rstrip(".").strip()
    return text

def get_context() -> str:
    # Minimal context (safe-ish): changed files + diff stats
    files = sh("git", "show", "--name-only", "--pretty=format:", "-1")
    stat  = sh("git", "show", "--stat", "--pretty=format:", "-1")
    return f"Files changed:\n{files}\n\nDiff stat:\n{stat}"

def in_range(s: str) -> bool:
    return SUBJECT_MIN <= len(s) <= SUBJECT_MAX and "\n" not in s

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: ai_subject_coach.py <commit_msg_file>", file=sys.stderr)
        return 2

    msg_file = sys.argv[1]
    original_full = open(msg_file, "r", encoding="utf-8").read()
    current_subject, _ = split_message(original_full)

    # If structure/body is broken, we refuse (subject-only coach)
    # We detect the most common structural issues:
    lines = original_full.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) < 3 or lines[1] != "" or not any(l.strip() for l in lines[2:]):
        print("❌ AI coach runs only when the structure/body is already correct.")
        print("Fix these first (deterministic):")
        print("- Blank line after subject (line 2)")
        print("- Non-empty body")
        print("- Body wrapped to <= 75 chars per line")
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

    if not in_range(suggestion):
        print("❌ Suggestion does not meet the subject length requirement.", file=sys.stderr)
        return 1

    ans = input("Apply this subject automatically? (y/n): ").strip().lower()
    if ans != "y":
        print("Not applied. Please amend manually and retry push.")
        return 1

    rc = apply_new_subject(suggestion, original_full)
    if rc != 0:
        print("❌ Failed to amend commit.", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())