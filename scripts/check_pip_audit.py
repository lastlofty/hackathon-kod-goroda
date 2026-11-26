"""Treat known vulnerabilities as findings, but fail on scanner errors."""

import json
import sys
from pathlib import Path


def main(report: Path, status: int) -> int:
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        dependencies = data["dependencies"]
        if not isinstance(dependencies, list) or not dependencies:
            raise ValueError("empty or invalid dependency list")
        findings = 0
        skipped = 0
        for dependency in dependencies:
            if "skip_reason" in dependency:
                skipped += 1
                continue
            vulnerabilities = dependency["vulns"]
            if not isinstance(vulnerabilities, list):
                raise ValueError("invalid vulnerability list")
            findings += len(vulnerabilities)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"::error::pip-audit did not produce a valid report: {exc}")
        return 1
    if status not in (0, 1) or (status == 1 and not findings):
        print(f"::error::pip-audit failed with exit code {status}")
        return 1
    if findings or skipped:
        print(f"::warning::pip-audit: {findings} findings, {skipped} skipped packages; review artifact")
    else:
        print("pip-audit: no known vulnerabilities found")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), int(sys.argv[2])))
