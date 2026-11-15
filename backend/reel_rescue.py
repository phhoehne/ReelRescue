#!/usr/bin/env python3
"""Reel Rescue: local, non-destructive VCD/SVCD recovery and video exports.

Stdlib only. FFmpeg/ffprobe are required for exports; GNU ddrescue for capture.
The native app exchanges newline-delimited JSON events with this process.
"""
from __future__ import annotations
import argparse
import collections
import ctypes
import datetime as dt
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
SYNC = b"\0" + b"\xff" * 10 + b"\0"
RAW = 2352
MAX_SECTORS = 100 * 60 * 75  # Bound damaged address fields and allocations.
ACTIVE = None


class RescueError(Exception):
    pass


class Cancelled(Exception):
    pass


def emit(kind, **fields):
    print(json.dumps(dict(type=kind, **fields)), flush=True)


def progress(phase, fraction=None, detail=""):
    emit("progress", phase=phase, fraction=fraction, detail=detail)


def cancel(signum, frame):
    raise Cancelled()


def tool(name, required=True):
    runtime = Path(sys.executable).resolve().parent.parent
    bundled = runtime / "bin" / name
    if getattr(sys, "frozen", False):
        candidates = [str(bundled)]
    else:
        candidates = [str(Path(os.environ.get("REEL_RESCUE_TOOL_DIR", HERE / "../build/vendor/payload/bin")) / name), shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}"]
    for p in candidates:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    if required:
        raise RescueError(f"The built-in {name} tool is missing. Reinstall Reel Rescue from a complete release download.")
    return None


def doctor():
    return {"python": sys.executable, "tools": {n: tool(n, False) for n in ("ffmpeg", "ffprobe", "ddrescue")},
            "checksum_accelerator": (HERE / "edc.dylib").exists()}


def dump(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd, log, phase, duration=None, read_progress=None):
    """Run only an argument array, never shell text; cancel the entire child group."""
    global ACTIVE
    dump(Path(log).with_suffix(".command.json"), cmd)
    last = 0
    with open(log, "w") as err:
        try:
            ACTIVE = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err,
                                      text=True, start_new_session=True, bufsize=1)
            if read_progress is not None:
                while ACTIVE.poll() is None:
                    read_progress()
                    try:
                        ACTIVE.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                read_progress()
            else:
                for line in ACTIVE.stdout:
                    text = line.strip()
                    if text.startswith("out_time_us="):
                        try:
                            seconds = int(text.split("=", 1)[1]) / 1e6
                        except ValueError:
                            continue
                        if time.monotonic() - last > .4:
                            progress(phase, min(.999, seconds / duration) if duration else None,
                                     f"{seconds / 60:.1f} minutes processed")
                            last = time.monotonic()
            code = ACTIVE.wait()
            if code:
                tail = Path(log).read_text(errors="replace")[-1800:]
                raise RescueError(f"{phase} failed (exit {code}). {tail}")
        finally:
            if ACTIVE is not None and ACTIVE.poll() is None:
                os.killpg(ACTIVE.pid, signal.SIGINT)
                try:
                    ACTIVE.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(ACTIVE.pid, signal.SIGKILL)
                    ACTIVE.wait()
            if ACTIVE is not None and ACTIVE.stdout is not None:
                ACTIVE.stdout.close()
            ACTIVE = None


_lib = None
_table = []
try:
    _lib = ctypes.CDLL(str(HERE / "edc.dylib"))
    _lib.init()
    _lib.edc.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    _lib.edc.restype = ctypes.c_uint32
except OSError:
    for i in range(256):
        x = i
        for _ in range(8):
            x = (x >> 1) ^ (0xD8018001 if x & 1 else 0)
        _table.append(x)


def edc(data):
    if _lib:
        return _lib.edc(data, len(data))
    c = 0
    for b in data:
        c = (c >> 8) ^ _table[(c ^ b) & 255]
    return c


def address(s):
    if len(s) != RAW or s[:12] != SYNC:
        return None
    h = s[12:15]
    if any(x % 16 > 9 or x // 16 > 9 for x in h):
        return None
    m, sec, frame = (x // 16 * 10 + x % 16 for x in h)
    if sec >= 60 or frame >= 75:
        return None
    a = (m * 60 + sec) * 75 + frame - 150
    return a if 0 <= a < MAX_SECTORS else None


def integrity(s):
    if address(s) is None:
        return "invalid"
    if s[15] == 1:
        return "valid" if edc(s[:2064]) == int.from_bytes(s[2064:2068], "little") else "invalid"
    if s[15] != 2 or s[16:20] != s[20:24]:
        return "invalid"
    end = 2348 if s[18] & 32 else 2072
    stored = int.from_bytes(s[end:end + 4], "little")
    if edc(s[16:end]) == stored:
        return "valid"
    # Form 2 EDC may be absent on some authored CDs. Do not call it verified.
    return "no_edc" if end == 2348 and stored == 0 else "invalid"


def raw_image(path):
    size = path.stat().st_size
    if size < RAW:
        raise RescueError(f"{path.name} is too small to be a raw CD image.")
    with path.open("rb") as f:
        head = f.read(RAW * 512)
    n = len(head) // RAW
    count = sum(head[i * RAW:i * RAW + 12] == SYNC for i in range(n))
    if count < max(1, n // 4):
        raise RescueError(f"{path.name} is not a 2,352-byte raw CD image. This recovery mode supports raw VCD/SVCD images, not ordinary DVD or 2,048-byte ISO images. Use Improve a video for an extracted MPEG file.")


def merge_images(paths, output, expected_sectors=None, report_path=None):
    """Index by recorded LBA, including disordered inputs; flag valid conflicts."""
    paths = [Path(p).resolve() for p in paths]
    if not paths or len(paths) > 16:
        raise RescueError("Choose between one and sixteen disc images.")
    handles, maps = [], []
    chosen, verified, conflicts = {}, {}, set()
    summaries = []
    try:
        for k, path in enumerate(paths):
            raw_image(path)
            f = path.open("rb"); handles.append(f)
            data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ); maps.append(data)
            n = len(data) // RAW
            if n > MAX_SECTORS:
                raise RescueError("This image is larger than a supported CD. DVD/Blu-ray recovery is not supported.")
            stats = collections.Counter()
            seen = set()
            for i in range(n):
                s = data[i * RAW:(i + 1) * RAW]
                a = address(s)
                if a is None or (expected_sectors and a >= expected_sectors):
                    stats["bad_address"] += 1; continue
                # A misread address is not protected by Mode 2 EDC. Reject extreme
                # jumps in whole-disc images instead of allocating to a corrupt LBA.
                if n > 10000 and abs(a - i) > 10000:
                    stats["implausible_address"] += 1; continue
                state = integrity(s); stats[state] += 1; seen.add(a)
                ref = (k, i)
                if state == "valid":
                    if a in verified:
                        pk, pi = verified[a]
                        if maps[pk][pi * RAW:(pi + 1) * RAW] != s:
                            conflicts.add(a)
                    else:
                        verified[a] = ref
                    chosen[a] = verified[a]
                elif a not in chosen:
                    chosen[a] = ref
                if i % 8192 == 0:
                    progress("Comparing disc sectors", (k + i / n) / len(paths), path.name)
            summaries.append(dict(file=str(path),sha256=sha(path),sectors=n,
                                  trailing_bytes=len(data) % RAW,unique_addresses=len(seen),counts=dict(stats)))
        if not chosen:
            raise RescueError("No usable CD sector addresses were found.")
        end = expected_sectors or max(chosen) + 1
        if not 0 < end <= MAX_SECTORS:
            raise RescueError("The recovered disc size is not plausible.")
        missing, invalid = [], []
        with Path(output).open("xb") as out:
            for a in range(end):
                ref = chosen.get(a)
                if ref is None:
                    out.write(bytes(RAW)); missing.append(a)
                else:
                    k, i = ref; out.write(maps[k][i * RAW:(i + 1) * RAW])
                    if a not in verified:
                        invalid.append(a)
        report = dict(sectors=end,verified_sectors=len(set(verified) - conflicts),
                      missing_lbas=missing,unverified_lbas=invalid,conflicting_lbas=sorted(conflicts),
                      unresolved_lbas=sorted(set(missing) | set(invalid) | conflicts),inputs=summaries,
                      note="EDC does not protect Mode 2 address bytes. Verification is sector-level evidence, not proof of perfect footage. Conflicting valid reads are retained but never counted as verified.")
        dump(report_path or Path(output).with_suffix(".json"), report)
        return report
    finally:
        for m in maps: m.close()
        for f in handles: f.close()


def iso_tracks(path):
    """Read the small ISO9660 directory, but extract Form 2 video as 2324 bytes."""
    with Path(path).open("rb") as f:
        total = Path(path).stat().st_size // RAW
        def sec(n):
            if not 0 <= n < total: raise RescueError("Directory points outside the disc image.")
            f.seek(n * RAW); s = f.read(RAW)
            if integrity(s) != "valid": raise RescueError("The disc directory is damaged. Supply a CUE sheet or recover the directory with another read.")
            return s[16:2064] if s[15] == 1 else s[24:2072]
        pvd = sec(16)
        if pvd[:7] != b"\x01CD001\x01": raise RescueError("No intact disc directory was found. Add the original CUE sheet to locate its video tracks.")
        def directory(ext, size):
            if size > 8 * 1024 * 1024: raise RescueError("Invalid CD directory size.")
            d = b"".join(sec(n) for n in range(ext, ext + (size + 2047) // 2048)); pos = 0; rows = []
            while pos < min(len(d), size):
                n = d[pos]
                if not n: pos = (pos // 2048 + 1) * 2048; continue
                r = d[pos:pos + n]
                if n < 34 or len(r) != n or 33 + r[32] > n: raise RescueError("Invalid CD directory entry.")
                rows.append((r[33:33 + r[32]].decode("ascii", "replace").split(";")[0],
                             int.from_bytes(r[2:6], "little"),int.from_bytes(r[10:14], "little"),r[25]))
                pos += n
            return rows
        roots = directory(int.from_bytes(pvd[158:162], "little"), int.from_bytes(pvd[166:170], "little"))
        tracks = []
        for name, ext, size, flags in roots:
            if name.upper() in ("MPEG2", "MPEGAV") and flags & 2:
                for filename, start, length, fileflags in directory(ext, size):
                    if re.match(r"AVSEQ\d+\.(MPG|DAT)$", filename, re.I):
                        end = start + (length + 2047) // 2048
                        if not start < end <= total: raise RescueError("Video extent is outside the image.")
                        tracks.append(dict(name=filename,start=start,end=end))
        if not tracks: raise RescueError("No VCD/SVCD AVSEQ tracks were found. Choose an extracted video instead.")
        return sorted(tracks, key=lambda t: t["start"])


def cue_tracks(path, total):
    text = Path(path).read_text(errors="replace")
    if len(re.findall(r"^\s*FILE\s", text, re.M | re.I)) != 1:
        raise RescueError("Use a single-file, whole-disc CUE sheet. Multi-file CUE layouts are not supported yet.")
    tracks = []; kind = ""
    for line in text.splitlines():
        m = re.match(r"\s*TRACK\s+(\d+)\s+(\S+)", line, re.I)
        if m: kind = m[2].upper()
        m = re.match(r"\s*INDEX\s+01\s+(\d+):(\d+):(\d+)", line, re.I)
        if m and kind == "MODE2/2352":
            minute, sec, frame = map(int, m.groups())
            if sec >= 60 or frame >= 75: raise RescueError("Invalid CUE timestamp.")
            tracks.append(dict(name=f"Track {len(tracks)+1}", start=(minute * 60 + sec) * 75 + frame))
    if not tracks: raise RescueError("The CUE sheet contains no Mode 2 tracks.")
    for i, t in enumerate(tracks):
        t["end"] = tracks[i+1]["start"] if i+1 < len(tracks) else total
        if not 0 <= t["start"] < t["end"] <= total: raise RescueError("CUE track boundaries do not fit this whole-disc image.")
    return tracks


def extract_tracks(image, tracks, folder):
    folder = Path(folder); folder.mkdir()
    outputs = []
    with Path(image).open("rb") as f:
        for num, track in enumerate(tracks, 1):
            p = folder / f"Track_{num:02d}.mpg"; bad = packs = 0
            with p.open("xb") as out:
                f.seek(track["start"] * RAW)
                for a in range(track["start"], track["end"]):
                    s = f.read(RAW)
                    if len(s) != RAW: raise RescueError("Unexpected end of disc image.")
                    if integrity(s) != "valid" or address(s) != a: bad += 1
                    # Skip filesystem Form 1 sectors and zero pregap/padding.
                    # Keep damaged payloads, including damaged MPEG pack headers.
                    if s[15] == 2 and (s[18] & 32 or s[22] & 32):
                        payload = s[24:2348]
                        if payload.strip(b"\0"):
                            out.write(payload); packs += payload.count(b"\0\0\1\xba")
            if not packs: p.unlink(); continue  # CUE data track, not a video track.
            outputs.append(dict(file=str(p),track=track,unverified_sectors=bad))
    if not outputs: raise RescueError("No MPEG program streams were found within those track boundaries.")
    return outputs


def disk_info(device):
    if not re.fullmatch(r"/dev/r?disk\d+", device):
        raise RescueError("Select a whole optical disc from the device list.")
    node = device.replace("/dev/rdisk", "/dev/disk")
    try:
        info = plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil","info","-plist",node],stderr=subprocess.DEVNULL,timeout=12))
    except Exception as e:
        raise RescueError("macOS could not inspect this disc. Insert it and refresh the device list.") from e
    optical = info.get("OpticalDeviceType") or info.get("OpticalMediaType") or info.get("Content") == "CD_partition_scheme"
    if not info.get("WholeDisk", info.get("Whole", False)) or not optical:
        raise RescueError("This device is not a whole optical disc. Hard drives and partitions are never accepted.")
    if any(info.get(k) is True for k in ("Writable", "WritableMedia")) or info.get("MediaReadOnly") is False:
        raise RescueError("The selected media is not read-only. Only recorded optical media can be captured.")
    if int(info.get("DeviceBlockSize", 0)) != RAW:
        raise RescueError("This disc does not expose 2,352-byte raw CD sectors. This version supports VCD/SVCD CDs, not DVDs or Blu-rays.")
    size = int(info.get("TotalSize", info.get("Size", 0)))
    if not RAW <= size <= MAX_SECTORS * RAW or size % RAW:
        raise RescueError("The optical disc size is not plausible.")
    return dict(device=node,raw_device=node.replace("/dev/disk", "/dev/rdisk"),size=size,
                sector_size=RAW,name=info.get("MediaName", info.get("DeviceOrMediaName", node)),
                identity={k: info.get(k) for k in ("DeviceIdentifier","MediaName","TotalSize","DeviceBlockSize","BusProtocol")})


def disc_inventory():
    """Report supported inserted media, attached empty drives, and inspection errors."""
    try:
        listing = plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil", "list", "-plist"],
            stderr=subprocess.DEVNULL, timeout=12))
    except Exception:
        return dict(discs=[], message="macOS could not list attached discs. Check the drive connection and refresh.")
    results, rejected = [], []
    for d in listing.get("AllDisksAndPartitions", []):
        # Include unknown layouts; disk_info still rejects non-optical devices.
        if d.get("Content", "") not in ("CD_partition_scheme", "", "Apple_partition_scheme"):
            continue
        identifier = d.get("DeviceIdentifier", "")
        if not re.fullmatch(r"disk\d+", identifier):
            continue
        try:
            results.append(disk_info("/dev/" + identifier))
        except RescueError as e:
            if d.get("Content") == "CD_partition_scheme":
                rejected.append(str(e))
    if results:
        return dict(discs=results, message="Inserted CD detected. Ready to recover.")
    if rejected:
        return dict(discs=[], message="CD detected: " + " ".join(dict.fromkeys(rejected)))
    try:
        hardware = json.loads(subprocess.check_output(["/usr/sbin/system_profiler", "SPDiscBurningDataType", "-json"],
            stderr=subprocess.DEVNULL, timeout=8)).get("SPDiscBurningDataType", [])
        if hardware:
            names = ", ".join(d.get("_name", "Optical drive") for d in hardware)
            return dict(discs=[], message=f"Drive connected: {names}. No supported readable CD is available yet. Insert a VCD/SVCD and refresh.")
    except Exception:
        pass
    return dict(discs=[], message="No readable CD detected. Connect an optical drive and insert a VCD/SVCD, or choose local files.")


def discs():
    return disc_inventory()["discs"]


def rescued_bytes(mapfile, total):
    """Count the bounded read domain; raw devices may have an open-ended tail."""
    try:
        rows = []
        for line in Path(mapfile).read_text().splitlines():
            fields = line.split()
            if len(fields) != 3 or fields[2] not in ("?","*","/","-","+"): continue
            try:
                position, size = (int(value,16) if value.lower().startswith("0x") else int(value,10) for value in fields[:2])
            except ValueError:
                return None
            if size <= 0 or position < 0: return None
            rows.append((position,size,fields[2]))
        cursor = rescued = 0
        for position,size,status in rows:
            # A raw device has no regular-file length. ddrescue therefore keeps
            # an untried tail up to LLONG_MAX even when --size bounds this read.
            # Only intervals intersecting the actual read domain contribute.
            if position >= total: continue
            end = min(position+size,total)
            if position != cursor: return None
            if status == "+": rescued += end-position
            cursor = end
        return rescued if cursor == total else None
    except (OSError,UnicodeError):
        return None


class CDReadProgress:
    def __init__(self, mapfile, total, clock=time.monotonic):
        self.mapfile, self.total, self.clock = mapfile,total,clock
        self.started = self.last_change = clock()
        self.samples = collections.deque([(self.started,0)])
        self.rescued = 0

    def __call__(self):
        now = self.clock()
        rescued = rescued_bytes(self.mapfile,self.total)
        if rescued is not None and rescued >= self.rescued:
            if rescued > self.rescued: self.last_change = now
            self.rescued = rescued
            self.samples.append((now,rescued))
        while len(self.samples)>2 and self.samples[1][0] < now-10:
            self.samples.popleft()
        elapsed = now-self.samples[0][0]
        rate = (self.rescued-self.samples[0][1])/elapsed if elapsed>0 else 0
        stalled = now-self.last_change >= 5
        remaining = self.total-self.rescued
        eta = remaining/rate if elapsed>=1 and rate>0 and not stalled and remaining>0 else None
        fraction = self.rescued/self.total
        detail = f"{fraction*100:.1f}% · {self.rescued/1e6:.1f} / {self.total/1e6:.1f} MB"
        if eta is not None:
            seconds = max(1,math.ceil(eta))
            if seconds>=3600: estimate=f"{seconds//3600}h {(seconds%3600)//60}m"
            elif seconds>=60: estimate=f"{seconds//60}m {seconds%60}s"
            else: estimate=f"{seconds}s"
            detail += " · Est. " + estimate + " remaining"
        elif remaining==0: detail += " · Finishing"
        elif stalled: detail += " · Waiting for drive"
        else: detail += " · Estimating time remaining"
        emit("progress",phase="Reading the CD",fraction=fraction,detail=detail,
             eta_seconds=eta,bytes_read=self.rescued,total_bytes=self.total)


def capture(device, folder, expected=None, diagnostics=None):
    info = disk_info(device)
    if expected and info["identity"] != expected:
        raise RescueError("The selected drive or disc changed. Refresh the list and select it again.")
    image = folder / "disc_read.bin"; mapfile = folder / "disc_read.map"
    # No force, output overwrite, device writes, unmounts or sudo commands.
    cmd = [tool("ddrescue"),"-q","-n","--mapfile-interval=1,5","-b",str(RAW),"-s",str(info["size"]),
           info["raw_device"],str(image),str(mapfile)]
    progress("Reading the CD",0,"Estimating time remaining")
    run(cmd, (diagnostics or folder) / "capture.log", "Reading the CD",
        read_progress=CDReadProgress(mapfile,info["size"]))
    progress("Reading the CD",1,"Read pass finished")
    return image, info


def retry(device, report, folder, expected=None, diagnostics=None):
    info = disk_info(device)
    if expected and info["identity"] != expected: raise RescueError("The disc changed before the retry pass.")
    targets = report["unresolved_lbas"]
    if not targets: return None
    # Bound repeated stress on a failing disc. Save all results for another session.
    if len(targets) > 2000:
        emit("warning", message="More than 2,000 sectors remain uncertain. Automatic retries were skipped; try another optical drive.")
        return None
    out = folder / "retry_reads.bin"; records = []; remaining = set(targets)
    fd = os.open(info["raw_device"], os.O_RDONLY)
    try:
        with out.open("xb") as f:
            for attempt in range(2):
                pending = sorted(remaining, reverse=bool(attempt))
                for n, a in enumerate(pending):
                    try:
                        s = os.pread(fd, RAW, a * RAW)
                        good = address(s) == a and integrity(s) == "valid"
                        if len(s) == RAW: f.write(s); f.flush()
                        if good: remaining.remove(a)
                        records.append(dict(lba=a,attempt=attempt+1,valid=good))
                    except OSError as e:
                        records.append(dict(lba=a,attempt=attempt+1,error=str(e)))
                    dump((diagnostics or folder) / "retry_report.json",dict(attempts=records,remaining=sorted(remaining)))
                    progress("Retrying uncertain sectors", (attempt + (n+1)/len(pending))/2,
                             f"{len(targets)-len(remaining)} of {len(targets)} recovered")
                if not remaining: break
    finally: os.close(fd)
    return out if out.stat().st_size else None


def probe(path):
    try:
        return json.loads(subprocess.check_output([tool("ffprobe"),"-v","error","-show_format","-show_streams","-show_chapters","-of","json",str(path)],stderr=subprocess.DEVNULL))
    except subprocess.CalledProcessError as e:
        raise RescueError(f"{Path(path).name} cannot be read as a video.") from e


def timestamp(text):
    parts = str(text).strip().split(":")
    if not 1 <= len(parts) <= 3: raise RescueError("Use seconds or a time such as 01:23.5.")
    try: values = [float(p) for p in parts]
    except ValueError: raise RescueError("A repair time is not a number.")
    if any(not math.isfinite(v) or v < 0 for v in values): raise RescueError("Repair times must be positive finite numbers.")
    if any(v >= 60 for v in values[1:]): raise RescueError("Seconds and minutes in a time must be below 60.")
    value = 0
    for v in values: value = value * 60 + v
    return value


def ranges(text, duration, hold=False):
    result = []
    if not text or not str(text).strip(): return result
    for line in re.split(r"[\n,;]+", str(text)):
        if not line.strip(): continue
        pair = re.split(r"\s*[-–]\s*", line.strip())
        if len(pair) != 2: raise RescueError("Write each repair range as start-end, for example 01:23.4-01:24.0.")
        a, b = map(timestamp, pair)
        if not 0 <= a < b <= duration: raise RescueError("A repair range is outside the video duration.")
        if hold and (a < .1 or b-a > 2): raise RescueError("A frame hold must start after 0.1 seconds and last no more than 2 seconds.")
        result.append((a,b))
    result.sort()
    if len(result) > 50 or any(a < prev_b for (_,prev_b),(a,_) in zip(result,result[1:])):
        raise RescueError("Use no more than 50 non-overlapping repair ranges.")
    return result


def stream_hash(path, selector):
    return subprocess.check_output([tool("ffmpeg"),"-nostdin","-v","error","-i",str(path),"-map",selector,"-c","copy","-f","hash","-hash","sha256","-"],stderr=subprocess.DEVNULL).decode().strip()


def decoded_frames(path):
    # Container packet counts may include hidden preroll frames after a trim.
    data = json.loads(subprocess.check_output([tool("ffprobe"),"-v","error","-select_streams","v:0",
        "-count_frames","-show_entries","stream=nb_read_frames","-of","json",str(path)],stderr=subprocess.DEVNULL))
    value = data["streams"][0].get("nb_read_frames")
    return int(value) if value and value != "N/A" else None


def export_video(source, folder, options, prefix="Film", recovering=False, preview=False):
    diagnostics = Path(folder) / "Diagnostics"
    diagnostics.mkdir(exist_ok=True)
    source = Path(source).resolve(); meta = probe(source)
    video = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    if not video: raise RescueError("The selected file contains no video stream.")
    duration = float(meta["format"].get("duration",0))
    if not math.isfinite(duration) or duration <= 0: raise RescueError("The video duration cannot be determined safely.")
    click_ranges = ranges(options.get("audio_ranges", ""), duration)
    holds = ranges(options.get("hold_ranges", ""), duration, True)
    if holds and preview: raise RescueError("Preview frame holds with a full export so absolute timing is preserved. Clear holds to make a short picture/audio preview.")
    preset = options.get("preset", "share")
    if preset not in ("native","hd","share"): raise RescueError("Unknown export preset.")
    filters = []
    interlaced = video.get("field_order") in ("tt","bb","tb","bt")
    if interlaced:
        filters.append("bwdif=mode=send_field:parity=auto:deint=all")
    if options.get("enhance", True):
        filters += ["hqdn3d=0.6:0.8:1.2:1.6","unsharp=5:5:0.5:5:5:0"]
    if preset in ("hd", "share"):
        # DAR (not stored width) governs geometry for anamorphic PAL/NTSC sources.
        filters += ["scale=w='if(gte(dar,16/9),1920,trunc(1080*dar/2)*2)':h='if(gte(dar,16/9),trunc(1920/dar/2)*2,1080)':flags=bicubic+accurate_rnd",
                    "setsar=1","pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"]
    else:
        filters += ["scale=w='trunc(ih*dar/2)*2':h=ih:flags=lanczos","setsar=1"]
    try:
        num, den = map(int,video.get("r_frame_rate","25/1").split("/")); fps = num / den
    except (ValueError, ZeroDivisionError): fps = 25
    if not 1 <= fps <= 120: fps = 25
    if interlaced: fps *= 2
    if holds:
        expression = "+".join(f"gte(t,{a})*lt(t,{b})" for a,b in holds)
        filters += [f"select='not({expression})'",f"fps={fps}:start_time={video.get('start_time','0')}"]
    elif recovering:
        filters.append(f"fps={fps}")
    final = folder / (prefix + ("_preview" if preview else "") + ".mp4")
    partial = final.with_name(final.stem + ".partial.mp4")
    start = timestamp(options.get("preview_start", "0")) if preview else 0
    if preview and (start >= duration or click_ranges):
        if click_ranges: raise RescueError("Clear audio ranges for a short picture preview; audio repair uses absolute times in a full export.")
        raise RescueError("Preview start is outside this video.")
    cmd = [tool("ffmpeg"),"-nostdin","-hide_banner","-n","-v","warning","-threads","2"]
    if preview: cmd += ["-ss",str(start)]
    cmd += ["-i",str(source),"-map","0:v:0","-map","0:a:0?","-map_metadata","0","-map_chapters","-1" if preview else "0","-vf",",".join(filters)]
    if preview: cmd += ["-t",str(min(10,duration-start))]
    audio_copy = bool(audio and audio["codec_name"] == "aac" and not click_ranges and not recovering)
    if audio:
        if audio_copy: cmd += ["-c:a","copy"]
        else:
            af = []
            if recovering: af.append("aresample=async=1:first_pts=0")
            if click_ranges:
                expression = "+".join(f"between(t,{a},{b})" for a,b in click_ranges)
                af += [f"adeclick=window=55:overlap=75:arorder=2:threshold=4:burst=2:method=save:enable='{expression}'",
                       "alimiter=limit=0.97:attack=5:release=50:level=false:latency=true"]
            if af: cmd += ["-af",",".join(af)]
            cmd += ["-c:a","aac","-b:a","256k"]
    hardware = preset != "native" and options.get("hardware", True)
    if preset == "share":
        enc = ["-c:v","hevc_videotoolbox","-q:v","65","-profile:v","main","-allow_sw","0","-prio_speed","false"] if hardware else ["-c:v","libx265","-preset","fast","-crf","22","-x265-params","pools=4:frame-threads=2:log-level=error"]
        enc += ["-tag:v","hvc1"]
    elif hardware:
        enc = ["-c:v","h264_videotoolbox","-q:v","85","-profile:v","high","-allow_sw","0","-prio_speed","false"]
    else:
        enc = ["-c:v","libx264","-preset","fast","-crf","17","-threads","4"]
    tail = ["-pix_fmt","yuv420p","-fps_mode","passthrough","-enc_time_base:v","1:1000","-video_track_timescale","1000","-movie_timescale","1000","-movflags","+faststart","-progress","pipe:1",str(partial)]
    log = diagnostics / (prefix + "_encode.log")
    try:
        run(cmd + enc + tail, log, "Rendering " + prefix, min(10,duration-start) if preview else duration)
    except RescueError:
        text = log.read_text(errors="replace")
        if hardware and any(t in text for t in ("Cannot create compression session", "hardware encoder may be busy")):
            if partial.exists(): partial.unlink()
            emit("warning",message="Hardware encoding is unavailable. Switching to the software encoder; this takes longer.")
            return export_video(source,folder,dict(options,hardware=False),prefix,recovering,preview)
        raise
    progress("Checking the finished video", None, "Checking playback, timing and audio")
    out = probe(partial); ov = next(s for s in out["streams"] if s["codec_type"] == "video")
    if not preview:
        drift = abs(float(out["format"]["duration"]) - duration)
        if drift > (max(2,duration*.002) if recovering else .15):
            raise RescueError("The export's duration changed unexpectedly.")
        if not interlaced and not recovering:
            source_frames = decoded_frames(source)
            if source_frames is not None and int(ov.get("nb_frames",0)) != source_frames:
                raise RescueError("The export changed the decoded frame count unexpectedly.")
        if len(out.get("chapters",[])) != len(meta.get("chapters",[])):
            raise RescueError("The chapter count changed unexpectedly.")
    if preset in ("hd","share") and (ov["width"],ov["height"]) != (1920,1080): raise RescueError("Unexpected output size.")
    audio_same = None
    if audio_copy and not preview:
        audio_same = stream_hash(source,"0:a:0") == stream_hash(partial,"0:a:0")
        if not audio_same: raise RescueError("The copied audio did not match the source.")
    run([tool("ffmpeg"),"-nostdin","-hide_banner","-v","error","-threads","4","-i",str(partial),"-map","0:v:0","-map","0:a:0?","-progress","pipe:1","-f","null","-"],
        diagnostics / (prefix + "_decode.log"), "Validating playback", float(out["format"]["duration"]))
    if (diagnostics / (prefix + "_decode.log")).read_text().strip():
        raise RescueError("The exported video reported decoding errors.")
    partial.rename(final)
    record = dict(file=str(final),source=str(source),preset=preset,preview=preview,
                  duration=out["format"]["duration"],width=ov["width"],height=ov["height"],
                  frames=ov.get("nb_frames"),audio_bitstream_identical=audio_same,
                  audio_ranges=click_ranges,hold_ranges=holds,hardware_encoder=hardware,
                  sha256=sha(final),source_sha256=sha(source),decode_errors=0)
    dump(diagnostics / (prefix + "_validation.json"),record)
    return record


def project(destination):
    root = Path(destination).expanduser().resolve()
    if not root.is_dir(): raise RescueError("Choose an existing output folder.")
    p = root / ("Reel Rescue " + dt.datetime.now().strftime("%Y-%m-%d %H%M%S") + "-" + uuid.uuid4().hex[:6])
    p.mkdir(); return p


def publish_video(source, destination):
    """Publish a verified video across volumes, leaving no failed copy in output."""
    source, destination = Path(source), Path(destination)
    if destination.exists(): raise RescueError("A video with this name already exists; it was not overwritten.")
    partial = destination.with_name("." + destination.stem + ".partial" + destination.suffix)
    owned = False
    try:
        with source.open("rb") as src, partial.open("xb") as out:
            owned = True
            shutil.copyfileobj(src, out, length=8 * 1024 * 1024)
        if sha(partial) != sha(source): raise RescueError("The saved video copy failed its checksum check.")
        partial.replace(destination)
    except BaseException:
        if owned and partial.exists(): partial.unlink()
        raise


def combine_tracks(sources, folder):
    if len(sources) < 2: raise RescueError("Choose at least two recovered tracks to combine.")
    paths = [Path(source).resolve() for source in sources]
    metadata = [probe(path) for path in paths]
    def signature(meta):
        video = next((v for v in meta["streams"] if v["codec_type"] == "video"), None)
        audio = [a for a in meta["streams"] if a["codec_type"] == "audio"]
        if not video or video["codec_name"] not in ("mpeg1video", "mpeg2video"):
            raise RescueError("Combine tracks accepts recovered MPEG-1/MPEG-2 videos.")
        if any(stream["codec_type"] not in ("audio","video") for stream in meta["streams"]):
            raise RescueError("These tracks contain additional streams that cannot be safely combined. The original tracks remain separate.")
        return ((video["codec_name"],video["width"],video["height"],video.get("sample_aspect_ratio")),
                tuple((a["codec_name"],a.get("sample_rate"),a.get("channels")) for a in audio))
    signatures = [signature(meta) for meta in metadata]
    if any(value != signatures[0] for value in signatures[1:]):
        raise RescueError("These tracks use different picture or sound formats and cannot be joined without conversion.")
    selectors = ["0:v:0"] + [f"0:a:{i}" for i in range(len(signatures[0][1]))]
    container = "vob" if signatures[0][0][0] == "mpeg2video" else "mpeg"
    normalized = []
    for index,(path,meta) in enumerate(zip(paths,metadata),1):
        target = folder / f"normalized_{index:02d}.mpg"
        run([tool("ffmpeg"),"-nostdin","-hide_banner","-v","warning","-n",
             "-fflags","+genpts","-dts_delta_threshold","10","-i",str(path),
             "-map","0:v:0","-map","0:a?","-c","copy",
             "-bsf:v","setts=pts='if(gt(abs(PTS-DTS),1/TB),DTS+DURATION,PTS)'","-f",container,
             "-progress","pipe:1",str(target)],folder / f"prepare_{index:02d}.log",
            f"Preparing track {index} of {len(paths)}",float(meta["format"]["duration"]))
        if signature(probe(target)) != signatures[0]:
            raise RescueError("Preparing a track changed its format unexpectedly.")
        for selector in selectors:
            if stream_hash(path,selector) != stream_hash(target,selector):
                raise RescueError("Preparing a track changed its compressed picture or sound data.")
        normalized.append(target)
    durations = [float(probe(path)["format"]["duration"]) for path in normalized]
    listing = folder / "tracks.ffconcat"
    lines = ["ffconcat version 1.0"]
    for path, duration in zip(normalized,durations):
        if "\n" in str(path) or "\r" in str(path): raise RescueError("Track filenames cannot contain newlines.")
        quoted = str(path).replace("'", "'\\''")
        lines += ["file '" + quoted + "'", "duration " + str(duration)]
    listing.write_text("\n".join(lines) + "\n")
    final = folder / "Combined.mpg"
    run([tool("ffmpeg"),"-nostdin","-hide_banner","-v","warning","-n","-f","concat","-safe","0", "-i",str(listing),
         "-map","0:v:0","-map","0:a?","-c","copy","-f",container,"-progress","pipe:1",str(final)],
        folder / "combine.log", "Combining tracks", sum(durations))
    result = probe(final)
    if signature(result) != signatures[0]: raise RescueError("The combined video's format changed unexpectedly.")
    if abs(float(result["format"]["duration"]) - sum(durations)) > max(0.5, sum(durations)*0.002):
        raise RescueError(f"The combined video's timing changed unexpectedly (expected {sum(durations):.1f}s; got {float(result['format']['duration']):.1f}s).")
    progress("Checking combined video")
    for selector in selectors:
        expected_hash = subprocess.check_output([tool("ffmpeg"),"-nostdin","-v","error","-f","concat","-safe","0",
            "-i",str(listing),"-map",selector,"-c","copy","-f","hash","-hash","sha256","-"],stderr=subprocess.DEVNULL).decode().strip()
        if expected_hash != stream_hash(final,selector):
            raise RescueError("The combined video changed compressed picture or sound data.")
    counts = [decoded_frames(path) for path in paths]
    video = next(stream for stream in result["streams"] if stream["codec_type"] == "video")
    try:
        numerator,denominator = map(int,video["r_frame_rate"].split("/"))
        fps = numerator/denominator
    except (KeyError,ValueError,ZeroDivisionError):
        raise RescueError("The combined video's frame timing cannot be verified.")
    if all(count is not None for count in counts) and fps>0:
        frame_duration = sum(counts)/fps
        if abs(float(result["format"]["duration"])-frame_duration)>max(2,frame_duration*0.01):
            raise RescueError("The combined video still contains an unsafe timestamp discontinuity.")
    if all(count is not None for count in counts) and decoded_frames(final) != sum(counts):
        raise RescueError("The combined video's frame count changed unexpectedly.")
    return dict(file=str(final),sha256=sha(final),stream_copy=True,combined_tracks=len(paths),
                timestamps_normalized=True,payloads_identical=True,frames=decoded_frames(final))


def job(config):
    # Raw reads, maps and processing records exist only during this run.
    with tempfile.TemporaryDirectory(prefix="ReelRescue-") as temporary:
        return run_job(config, Path(temporary))


def run_job(config, work):
    mode = config.get("mode")
    if mode not in ("video","images","disc","combine"): raise RescueError("Unknown task.")
    tool("ffmpeg"); tool("ffprobe")
    p = project(config["destination"])
    diagnostics = work / "Diagnostics"; diagnostics.mkdir()
    data = work / "Recovery data"
    rendered = work / "Rendered"; rendered.mkdir()
    if mode in ("images","disc"): data.mkdir()
    dump(diagnostics / "settings.json",config)
    emit("project",path=str(p))
    report = dict(status="running",mode=mode,project=str(p),layout_version=4,outputs=[])
    dump(diagnostics / "report.json",report)
    def export(source, options, prefix="Film", recovering=False, preview=False):
        record = export_video(source,rendered,options,prefix=prefix,recovering=recovering,preview=preview)
        staged = Path(record["file"])
        final = p / staged.name
        publish_video(staged,final)
        record["file"] = str(final)
        dump(rendered / "Diagnostics" / (prefix + "_validation.json"),record)
        staged.unlink()
        return record
    try:
        if mode == "video":
            sources = config.get("sources",[])
            if len(sources) != 1: raise RescueError("Choose one video at a time.")
            report["outputs"] = [export(sources[0],config,prefix="Film",preview=config.get("preview",False))]
        elif mode == "combine":
            record = combine_tracks(config.get("sources",[]),rendered)
            final = p / "Combined.mpg"
            publish_video(record["file"],final)
            record["file"] = str(final)
            report["outputs"] = [record]
        else:
            paths = list(config.get("sources",[])); info = None
            if mode == "disc":
                new, info = capture(config["device"],data,config.get("device_identity"),diagnostics); paths.insert(0,str(new))
            best = data / "recovered.bin"
            recovery = merge_images(paths,best,info["size"]//RAW if info else None,diagnostics / "recovered.json")
            if info and config.get("retry",True):
                patch = retry(info["device"],recovery,data,info["identity"],diagnostics)
                if patch:
                    best = data / "recovered_after_retry.bin"
                    recovery = merge_images(paths + [patch],best,info["size"]//RAW,diagnostics / "recovered_after_retry.json")
            report["recovery"] = recovery
            try: tracks = iso_tracks(best)
            except RescueError:
                if config.get("cue"): tracks = cue_tracks(config["cue"],recovery["sectors"])
                else: raise
            extracted = extract_tracks(best,tracks,data / "Original video")
            report["extracted"] = extracted
            dump(diagnostics / "report.json",report)
            # Recovery publishes the authored MPEG stream unchanged. Enhancement
            # and joining are separate post-processing operations.
            saved = []
            for item in extracted:
                final = p / Path(item["file"]).name
                publish_video(item["file"],final)
                output = dict(file=str(final),sha256=sha(final),original_stream=True)
                report["outputs"].append(output)
                saved.append(dict(item,file=str(final)))
            report["extracted"] = saved
            uncertain = len(recovery["unresolved_lbas"])
            emit("recovery",verified=recovery["verified_sectors"],total=recovery["sectors"],uncertain=uncertain)
            if uncertain: emit("warning",message=f"{uncertain:,} sectors remain missing, unverified or conflicting. Some visible or audible damage may remain.")
        report["status"] = "complete"; dump(diagnostics / "report.json",report)
        (diagnostics / "SHA256SUMS.txt").write_text("".join(x["sha256"] + "  " + x["file"] + "\n" for x in report["outputs"]))
        result = report["outputs"][0]["file"] if report["outputs"] else report.get("image",str(p))
        emit("complete",path=result,project=str(p),message="Finished and verified",report=report)
    except BaseException as e:
        report["status"] = "cancelled" if isinstance(e,Cancelled) else "failed"
        report["error"] = str(e); dump(diagnostics / "report.json",report)
        raise


def main():
    signal.signal(signal.SIGTERM,cancel); signal.signal(signal.SIGINT,cancel)
    parser = argparse.ArgumentParser(); parser.add_argument("command",choices=["doctor","discs","devices","job"]); parser.add_argument("path",nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "doctor": print(json.dumps(doctor()),flush=True)
        elif args.command == "discs": print(json.dumps(discs()),flush=True)
        elif args.command == "devices": print(json.dumps(disc_inventory()),flush=True)
        elif not args.path: raise RescueError("A job settings file is required.")
        else: job(json.loads(Path(args.path).read_text()))
    except Cancelled:
        emit("cancelled",message="Stopped. Temporary working files were removed."); return 130
    except Exception as e:
        emit("error",message=str(e)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
