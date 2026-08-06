"""Reject likely secrets and machine-specific data in staged text files."""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "network IPv4 address": re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b"),
    "machine-specific home path": re.compile(r"/(?:home|Users)/[^/<\s]+/"),
    "likely API credential": re.compile(
        r"(?i)(?:api[_-]?key|authorization)\s*[:=]\s*['\"]?(?!<|\$|GOOGLE_|OPENAI_|DEEPSEEK_|OLLAMA_)[A-Za-z0-9_-]{16,}"
    ),
}


def main() -> int:
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    violations: list[str] = []
    for name in names:
        content = subprocess.run(["git", "show", f":{name}"], capture_output=True).stdout
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{name}: {label}")
    if violations:
        print("Privacy check failed:\n" + "\n".join(violations))
        return 1
    print("Staged-file privacy check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
