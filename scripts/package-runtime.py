#!/usr/bin/env python3
"""Freeze the engine, bundle runtime tools and licenses, sign nested code."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "build/vendor"


def run(*args, **kwargs): return subprocess.run(args, check=True, **kwargs)


def is_macho(path):
    if path.is_symlink() or not path.is_file(): return False
    with path.open("rb") as stream:
        return stream.read(4) in (b"\xcf\xfa\xed\xfe",b"\xca\xfe\xba\xbe",b"\xfe\xed\xfa\xcf")


def sign(path):
    identity = os.environ.get("EXPANDED_CODE_SIGN_IDENTITY") or "-"
    args = ["codesign","--force","--sign",identity,"--options","runtime"]
    args += ["--timestamp=none"] if identity == "-" else ["--timestamp"]
    run(*args,str(path))


def main():
    python = VENDOR / "tools/bin/python"
    tools = VENDOR / "payload/bin"
    if not python.exists() or any(not (tools/n).exists() for n in ("ffmpeg","ffprobe","ddrescue")):
        raise SystemExit("Bundled runtime is not prepared. Run scripts/prepare-runtime.py with Python 3.12.10 first.")
    for item in json.loads((ROOT/"Config/RuntimeSources.json").read_text()):
        archive = VENDOR / "downloads" / item["file"]
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"Missing or changed redistribution source: {item['file']}")
    run("xcrun","clang","-arch","arm64","-mmacosx-version-min=14.0","-O3","-dynamiclib",
        str(ROOT/"backend/edc.c"),"-o",str(ROOT/"backend/edc.dylib"))
    run(str(python),"-m","PyInstaller","--noconfirm","--clean","--onedir","--name","ReelRescueEngine",
        "--target-architecture","arm64","--add-binary",str(ROOT/"backend/edc.dylib")+":.",
        "--distpath",str(VENDOR/"frozen"),"--workpath",str(VENDOR/"freeze-work"),
        "--specpath",str(VENDOR),str(ROOT/"backend/reel_rescue.py"))
    resources = Path(os.environ["TARGET_BUILD_DIR"]) / os.environ["UNLOCALIZED_RESOURCES_FOLDER_PATH"]
    runtime = resources / "runtime"
    if runtime.exists(): shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    shutil.copytree(VENDOR/"frozen/ReelRescueEngine",runtime/"engine",symlinks=True)
    shutil.copytree(tools,runtime/"bin")
    licenses = runtime / "licenses"; licenses.mkdir()
    for component, relative in [("FFmpeg","ffmpeg-8.0.1/COPYING.GPLv3"),("x264","x264-stable/COPYING"),
        ("x265","x265_4.1/COPYING"),("ddrescue","ddrescue-1.30/COPYING")]:
        shutil.copy(VENDOR/"src"/relative,licenses/(component+".txt"))
    import sysconfig
    # Read the license from the Python used to create this build's isolated tools.
    python_license = subprocess.check_output([str(python),"-c","import sysconfig;print(sysconfig.get_path('stdlib')+'/LICENSE.txt')"],text=True).strip()
    shutil.copy(python_license,licenses/"Python.txt")
    for archive_name, member_name, output in [("pyinstaller-6.16.0.tar.gz","pyinstaller-6.16.0/COPYING.txt","PyInstaller.txt"),
        ("openssl-3.0.16.tar.gz","openssl-3.0.16/LICENSE.txt","OpenSSL.txt")]:
        with tarfile.open(VENDOR/"downloads"/archive_name) as archive:
            (licenses/output).write_bytes(archive.extractfile(member_name).read())
    shutil.copy(ROOT/"THIRD_PARTY_NOTICES.md",licenses/"THIRD_PARTY_NOTICES.md")
    manifest = []
    # Sign leaf Mach-O files first, then the Python framework bundle.
    for path in runtime.rglob("*"):
        if is_macho(path):
            deps = subprocess.check_output(["otool","-L",str(path)],text=True)
            forbidden = [line for line in deps.splitlines()[1:] if line.strip().startswith(("/opt/","/usr/local/","/Library/Frameworks/"))]
            if forbidden: raise SystemExit(f"External runtime dependency in {path}: {forbidden}")
            build = subprocess.check_output(["vtool","-show-build",str(path)],text=True)
            import re
            for version in re.findall(r"minos (\d+)\.(\d+)",build):
                if tuple(map(int,version)) > (14,0): raise SystemExit(f"Runtime requires newer macOS: {path}")
            if os.environ.get("CODE_SIGNING_ALLOWED") != "NO": sign(path)
            manifest.append(dict(file=str(path.relative_to(runtime)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for path in runtime.rglob("*.framework"):
        if os.environ.get("CODE_SIGNING_ALLOWED") != "NO": sign(path)
    for item in manifest:
        item["sha256"] = hashlib.sha256((runtime/item["file"]).read_bytes()).hexdigest()
    (runtime/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    # Keep original Python backend for source transparency; execution uses the frozen engine.
    backend = resources/"backend"; backend.mkdir(exist_ok=True)
    shutil.copy(ROOT/"backend/reel_rescue.py",backend/"reel_rescue.py")
    if (backend/"edc.dylib").exists(): (backend/"edc.dylib").unlink()
    print("Bundled recovery engine, media tools, licenses and signing complete.")


if __name__ == "__main__": main()
