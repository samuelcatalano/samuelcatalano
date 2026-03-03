#!/usr/bin/env python3
import sys

SUBJECT_MIN = 60
SUBJECT_MAX = 75
LINE_MAX = 75

def validate(msg: str) -> list[str]:
    errors: list[str] = []
    msg = msg.replace("\r\n", "\n").replace("\r", "\n")
    lines = msg.split("\n")

    if not lines or not lines[0].strip():
        errors.append("Subject line is missing.")
        return errors

    subject = lines[0]
    subject_len = len(subject)
    if subject_len < SUBJECT_MIN or subject_len > SUBJECT_MAX:
        errors.append(
            f"Subject length must be {SUBJECT_MIN}-{SUBJECT_MAX} characters; got {subject_len}."
        )

    if len(lines) < 2 or lines[1] != "":
        errors.append("Line 2 must be blank (required blank line after subject).")

    body_lines = lines[2:] if len(lines) >= 3 else []
    if not any(l.strip() for l in body_lines):
        errors.append("Body is required (non-empty) after the blank line.")

    for i, line in enumerate(body_lines, start=3):
        if len(line) > LINE_MAX:
            errors.append(f"Body line {i} exceeds {LINE_MAX} chars (got {len(line)}).")

    return errors

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_commit_message.py <commit_msg_file>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    msg = open(path, "r", encoding="utf-8").read()
    errors = validate(msg)

    if errors:
        print("❌ Commit message validation failed.\n")
        print("Required format:")
        print(f"- Subject length: {SUBJECT_MIN}-{SUBJECT_MAX} chars")
        print("- Blank line on line 2")
        print(f"- Body lines wrapped to max {LINE_MAX} chars\n")
        print("Errors:")
        for e in errors:
            print(f"- {e}")
        print("\nTip: Write the message in English.")
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
