#!/usr/bin/env python3
"""Create the corresponding-source download shipped alongside bundled app releases."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
from version import ROOT


def create(folder, version, build):
    output = Path(folder) / f"ReelRescue-{version}-build{build}-dependency-sources.zip"
    items = json.loads((ROOT/"Config/RuntimeSources.json").read_text())
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_STORED) as archive:
        for item in items:
            source = ROOT/"build/vendor/downloads"/item["file"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
                raise SystemExit(f"Corresponding source checksum mismatch: {source.name}")
            archive.write(source,"archives/"+source.name)
        for name in ("Config/RuntimeSources.json","scripts/build-media-tools.sh","scripts/prepare-runtime.py",
                     "scripts/package-runtime.py","scripts/runtime-build-requirements.txt","backend/edc.c",
                     "backend/reel_rescue.py","THIRD_PARTY_NOTICES.md"):
            archive.write(ROOT/name,name)
        archive.writestr("README.txt", "Reel Rescue bundled dependency sources\n\n"
            "Publish this ZIP alongside the matching app ZIP. It contains the exact source archives,\n"
            "license texts within those archives, and build/packaging recipes for the bundled tools.\n"
            "FFmpeg 8.0.1 (GPL-3.0-or-later), x264 stable (GPL-2.0-or-later), x265 4.1\n"
            "(GPL-2.0-or-later), ddrescue 1.30 (GPL-2.0-or-later), Python 3.12.10 (PSF),\n"
            "OpenSSL 3.0.16 (Apache-2.0), and PyInstaller 6.16.0 (GPL-2.0-or-later with\n"
            "bootloader exception). Original archives are unmodified.\n\n"
            "Build with macOS Xcode tools, official python.org Python 3.12.10, and pkg-config.\n"
            "Place the archives into build/vendor/downloads, install isolated requirements from\n"
            "scripts/runtime-build-requirements.txt, and run scripts/prepare-runtime.py followed\n"
            "by the Xcode app build. See the matching Reel Rescue source tag for the full project.\n"
            "The media recipe targets macOS 14 arm64 and uses static x264/x265, VideoToolbox and\n"
            "AudioToolbox, with networking and automatic external-library discovery disabled.\n"
            "PyInstaller freezes the engine using the official Python 3.12.10 macOS framework,\n"
            "including its OpenSSL 3.0.16 libraries. CPython's Mac/BuildScript source describes\n"
            "that upstream framework build. The app signs nested executables without runtime\n"
            "entitlement exceptions. Signing identities are local and not included.\n")
    return output


if __name__ == "__main__":
    create(*sys.argv[1:])
