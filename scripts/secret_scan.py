"""Offline high-confidence secret scan for tracked and untracked source files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private-key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "telegram-token": re.compile(r"(?<![A-Za-z0-9_-])\d{5,16}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    "openai-key": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    "json-private-key": re.compile('"private_' + r'key"\s*:'),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".pdf", ".pyc"}


def source_paths() -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).split(b"\0")
    return [ROOT / raw.decode("utf-8") for raw in tracked if raw]


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in source_paths():
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((path.relative_to(ROOT).as_posix(), line_number, label))
    if findings:
        for relative, line_number, label in findings:
            print(f"{relative}:{line_number}: potential {label}", file=sys.stderr)
        return 1
    print("Secret scan passed; no high-confidence patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
