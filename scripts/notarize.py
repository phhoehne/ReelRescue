#!/usr/bin/env python3
"""Submit a signed release ZIP to Apple, staple its ticket and verify Gatekeeper."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from version import ROOT, current


def run(*args):
    return subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Existing notarytool Keychain profile name")
    args = parser.parse_args()
    version, build = current()
    folder = ROOT / "dist" / f"v{version}" / f"build-{build}"
    metadata = folder / "release.json"
    record = json.loads(metadata.read_text())
    if record["ad_hoc_signed"] or record["source_dirty"]:
        raise SystemExit("Package committed source with Developer ID signing before notarization.")
    archive = folder / record["archive"]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != record["sha256"]:
        raise SystemExit("Release checksum mismatch")
    submission_file = folder / "notarization.json"
    if submission_file.exists():
        result = json.loads(submission_file.read_text())
        if result.get("status") != "Accepted":
            result = json.loads(subprocess.check_output(["xcrun", "notarytool", "info", result["id"],
                "--keychain-profile", args.profile, "--output-format", "json"], text=True))
    else:
        # Submits app code to Apple's notary service. No credentials enter the repo.
        process = subprocess.run(["xcrun", "notarytool", "submit", str(archive),
            "--keychain-profile", args.profile, "--wait", "--output-format", "json"], capture_output=True, text=True)
        if not process.stdout.strip():
            raise SystemExit(process.stderr or "Notarization produced no submission result")
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError:
            raise SystemExit(process.stderr + process.stdout)
    submission_file.write_text(json.dumps(result, indent=2) + "\n")
    if result.get("status") != "Accepted":
        if result.get("id"):
            subprocess.run(["xcrun", "notarytool", "log", result["id"], "--keychain-profile", args.profile,
                str(folder / "notarization-log.json")], check=False)
        raise SystemExit(f"Notarization is {result.get('status')}; inspect notarization.json and the log.")
    with tempfile.TemporaryDirectory(prefix="reel-notarize-") as temp:
        run("ditto", "-x", "-k", str(archive), temp)
        app = Path(temp) / "Reel Rescue.app"
        fallback = False
        try:
            subprocess.run(["xcrun","stapler","staple",str(app)],check=True,timeout=30)
            subprocess.run(["xcrun","stapler","validate",str(app)],check=True,timeout=30)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            run("python3",str(ROOT/"scripts/apple-ticket.py"),str(app))
            fallback = True
        run("codesign", "--verify", "--deep", "--strict", str(app))
        run("spctl", "--assess", "--type", "execute", "--verbose=2", str(app))
        temporary = folder / (archive.name + ".stapled")
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(temporary))
        # Retain the exact upload for audit; GitHub receives the stapled ZIP.
        original = folder / "submitted.zip"
        if not original.exists():
            archive.rename(original)
        temporary.replace(archive)
        run("ditto", str(app), str(ROOT / "dist/Reel Rescue.app"))
    record.update(notarization="Accepted", notarization_submission=result["id"],
        stapled=True, ticket_attachment="HTTPS fallback" if fallback else "stapler", gatekeeper_assessment="accepted", sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    checksums = f"{record['sha256']}  {archive.name}\n"
    if record.get("dependency_sources"):
        checksums += f"{record['dependency_sources_sha256']}  {record['dependency_sources']}\n"
    (folder / "SHA256SUMS.txt").write_text(checksums)
    print(f"Signed, notarized, stapled and verified: {archive}")


if __name__ == "__main__":
    main()
