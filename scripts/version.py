#!/usr/bin/env python3
"""Show or increment the canonical app version. Never tags or publishes."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "Config/Version.xcconfig"


def current():
    text = CONFIG.read_text()
    version = re.search(r"^MARKETING_VERSION = (\d+\.\d+\.\d+)$", text, re.M)
    build = re.search(r"^CURRENT_PROJECT_VERSION = (\d+)$", text, re.M)
    if not version or not build:
        raise SystemExit("Invalid Config/Version.xcconfig")
    return version[1], int(build[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["show", "patch", "minor", "major", "build"], default="show", nargs="?")
    args = parser.parse_args()
    version, build = current()
    if args.action != "show":
        parts = list(map(int, version.split(".")))
        if args.action != "build":
            index = {"major": 0, "minor": 1, "patch": 2}[args.action]
            parts[index] += 1
            for i in range(index+1, 3):
                parts[i] = 0
        version = ".".join(map(str, parts))
        build += 1
        CONFIG.write_text("// Canonical release version and monotonically increasing build number.\n"
                          f"MARKETING_VERSION = {version}\nCURRENT_PROJECT_VERSION = {build}\n")
    print(f"{version} (build {build})")


if __name__ == "__main__":
    main()
