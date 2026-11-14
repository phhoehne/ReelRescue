#!/usr/bin/env python3
"""Build a local versioned release ZIP and checksums; never upload or tag."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
from version import ROOT, current


def main():
    version, build = current()
    subprocess.run([str(ROOT / "build.sh")], cwd=ROOT, check=True)
    app = ROOT / "dist/Reel Rescue.app"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if (info["CFBundleShortVersionString"], info["CFBundleVersion"]) != (version, str(build)):
        raise SystemExit("Built app version differs from the release configuration")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    folder = ROOT / "dist" / f"v{version}" / f"build-{build}"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"ReelRescue-{version}-build{build}-macOS-arm64.zip"
    if archive.exists():
        raise SystemExit("This release archive already exists. Increment the build number before packaging again.")
    temporary = folder / (archive.name + ".partial")
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(temporary)], check=True)
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (folder / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    signature = subprocess.run(["codesign", "-dvv", str(app)], capture_output=True, text=True, check=True).stderr
    (folder / "release.json").write_text(json.dumps(dict(version=version, build=build,
        suggested_tag=f"v{version}", source_commit=commit, source_dirty=dirty,
        archive=archive.name, sha256=digest, architecture="arm64", minimum_macos="14.0",
        ad_hoc_signed="Signature=adhoc" in signature,
        notarization="Not checked by this packaging tool",
        runtime_dependencies=["Python 3", "FFmpeg/ffprobe", "GNU ddrescue for physical CD capture"]), indent=2) + "\n")
    print(f"Release assets: {folder}")
    if dirty:
        print("Local preview package: source has uncommitted changes. Commit and rebuild before publishing.")


if __name__ == "__main__":
    main()
