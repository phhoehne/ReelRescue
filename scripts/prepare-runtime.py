#!/usr/bin/env python3
"""Developer-only setup for the pinned macOS 14+ bundled runtime."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "build/vendor"


def run(*args): subprocess.run(args, cwd=ROOT, check=True)


def main():
    if sys.version_info[:3] != (3,12,10):
        raise SystemExit("Build the embedded engine with official python.org Python 3.12.10 to match its source archive.")
    downloads = VENDOR / "downloads"; downloads.mkdir(parents=True,exist_ok=True)
    source = VENDOR / "src"; source.mkdir(exist_ok=True)
    for item in json.loads((ROOT / "Config/RuntimeSources.json").read_text()):
        archive = downloads / item["file"]
        if not archive.exists():
            run("curl","-fL","--retry","2","--connect-timeout","10","--max-time","180",item["url"],"-o",str(archive))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"Source checksum mismatch: {archive.name}")
        if item["file"] in ("x264-stable.tar.bz2","x265_4.1.tar.gz","ffmpeg-8.0.1.tar.xz","ddrescue-1.30.tar.lz"):
            run("tar","-xf",str(archive),"-C",str(source))
    run(sys.executable,"-m","venv",str(VENDOR / "tools"))
    python = str(VENDOR / "tools/bin/python")
    run(python,"-m","pip","install","--disable-pip-version-check","-r",str(ROOT / "scripts/runtime-build-requirements.txt"))
    run(str(ROOT / "scripts/build-media-tools.sh"))
    print("Media tools prepared. Run ./build.sh to package and sign the complete app.")


if __name__ == "__main__": main()
