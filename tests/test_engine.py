import contextlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rescue", ROOT / "backend/reel_rescue.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def sector(lba, fill=42, form2=True):
    s = bytearray(r.RAW)
    s[:12] = r.SYNC
    n = lba + 150
    for i, v in enumerate((n // 4500, n // 75 % 60, n % 75), 12):
        s[i] = (v // 10) * 16 + v % 10
    s[15] = 2
    s[16:20] = s[20:24] = bytes([1, 0, 0x20 if form2 else 0, 0])
    end = 2348 if form2 else 2072
    s[24:end] = bytes([fill]) * (end-24)
    s[end:end+4] = r.edc(bytes(s[16:end])).to_bytes(4, "little")
    return bytes(s)


class RecoveryTests(unittest.TestCase):
    def test_cancellation_stops_child_process(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); child_pid = p/"child.pid"
            script = f"""import sys, signal
sys.path.insert(0, {str(ROOT / 'backend')!r})
import reel_rescue as r
signal.signal(signal.SIGTERM, r.cancel)
try:
    r.run([sys.executable, '-c', {('import os,time,pathlib; pathlib.Path('+repr(str(child_pid))+').write_text(str(os.getpid())); time.sleep(60)')!r}], {str(p/'child.log')!r}, 'test')
except r.Cancelled:
    sys.exit(130)
"""
            process = subprocess.Popen([sys.executable,"-c",script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                until = time.monotonic()+5
                while not child_pid.exists() and time.monotonic()<until: time.sleep(.02)
                self.assertTrue(child_pid.exists())
                pid = int(child_pid.read_text())
                process.terminate()
                self.assertEqual(process.wait(timeout=6),130)
                import os
                with self.assertRaises(ProcessLookupError): os.kill(pid,0)
            finally:
                if process.poll() is None: process.kill(); process.wait()

    def test_crc_reference_vector_and_corruption(self):
        self.assertEqual(r.edc(b"123456789"), 0x6EC2EDC4)
        for form in (True, False):
            s = sector(1500, form2=form)
            self.assertEqual(r.address(s), 1500)
            self.assertEqual(r.integrity(s), "valid")
            bad = bytearray(s); bad[200] ^= 1
            self.assertEqual(r.integrity(bytes(bad)), "invalid")
        self.assertIsNone(r.address(bytes(2352)))

    def test_merges_by_address_and_reports_conflicts_missing(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p = Path(d); a = p/"a.iso"; b = p/"b.bin"
            bad = bytearray(sector(1)); bad[200] ^= 1
            a.write_bytes(sector(2) + sector(0) + bytes(bad))
            b.write_bytes(sector(1) + sector(2, fill=99))
            original = r.sha(a)
            report = r.merge_images([a,b],p/"out.bin",expected_sectors=4)
            self.assertEqual(report["verified_sectors"], 2)
            self.assertEqual(report["missing_lbas"], [3])
            self.assertEqual(report["conflicting_lbas"], [2])
            data = (p/"out.bin").read_bytes()
            self.assertEqual(data[2352:4704], sector(1))
            self.assertEqual(r.sha(a), original)
            with self.assertRaises(FileExistsError):
                r.merge_images([a],p/"out.bin")

    def test_rejects_ordinary_iso_and_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"ordinary.iso"; p.write_bytes(bytes(2048*20))
            with self.assertRaises(r.RescueError): r.raw_image(p)
        self.assertEqual(r.ranges("1:02-1:03\n70-71", 80), [(62,63),(70,71)])
        for text in ("-1-2", "nan-4", "2-1", "0-4;3-5", "1:99-2:00"):
            with self.assertRaises(r.RescueError): r.ranges(text, 200)
        with self.assertRaises(r.RescueError): r.ranges("1-4", 10, hold=True)

    def test_current_macos_wholedisk_metadata_disc_detection(self):
        info = dict(WholeDisk=True, Content="CD_partition_scheme", DeviceBlockSize=2352,
                    TotalSize=562292640, Writable=False, WritableMedia=False,
                    OpticalMediaType="CD-ROM", DeviceIdentifier="disk10", MediaName="USB optical drive")
        listing = dict(AllDisksAndPartitions=[dict(Content="CD_partition_scheme", DeviceIdentifier="disk10")])
        def output(command, **kwargs):
            return plistlib.dumps(listing if command[1] == "list" else info)
        with patch.object(r.subprocess, "check_output", side_effect=output):
            found = r.disc_inventory()
            self.assertEqual(found["discs"][0]["device"], "/dev/disk10")
        for changes in (dict(WholeDisk=False), dict(WritableMedia=True), dict(DeviceBlockSize=2048)):
            with patch.object(r.subprocess, "check_output", return_value=plistlib.dumps(dict(info, **changes))):
                with self.assertRaises(r.RescueError): r.disk_info("/dev/disk10")

    def test_drive_inventory_explains_unsupported_media_and_errors(self):
        listing = dict(AllDisksAndPartitions=[dict(Content="CD_partition_scheme", DeviceIdentifier="disk10")])
        with patch.object(r.subprocess,"check_output",return_value=plistlib.dumps(listing)), \
             patch.object(r,"disk_info",side_effect=r.RescueError("Unsupported sector size")):
            found = r.disc_inventory()
            self.assertEqual(found["discs"], [])
            self.assertIn("Unsupported sector size", found["message"])
        with patch.object(r.subprocess,"check_output",side_effect=subprocess.TimeoutExpired("diskutil",12)):
            self.assertIn("could not list",r.disc_inventory()["message"])
        with patch.object(r.subprocess,"check_output",side_effect=[plistlib.dumps(dict(AllDisksAndPartitions=[])),
             json.dumps(dict(SPDiscBurningDataType=[dict(_name="USB CD drive")])).encode()]):
            self.assertIn("Drive connected: USB CD drive", r.disc_inventory()["message"])

    def test_device_guard_rejects_writable_and_nonoptical(self):
        base = dict(Whole=True, Content="CD_partition_scheme", DeviceBlockSize=2352,
                    TotalSize=2352*1000, Writable=False, DeviceIdentifier="disk10")
        with patch.object(r.subprocess,"check_output",return_value=plistlib.dumps(base)):
            self.assertEqual(r.disk_info("/dev/disk10")["raw_device"], "/dev/rdisk10")
            with self.assertRaises(r.RescueError): r.disk_info("/dev/disk10s1")
        for change in (dict(Writable=True),dict(Content="GUID_partition_scheme"),dict(DeviceBlockSize=2048)):
            with patch.object(r.subprocess,"check_output",return_value=plistlib.dumps(dict(base,**change))):
                with self.assertRaises(r.RescueError): r.disk_info("/dev/disk10")


@unittest.skipUnless(r.tool("ffmpeg",False) and r.tool("ffprobe",False), "FFmpeg required")
class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.temp.name)
        cls.source = cls.folder/"anamorphic.mp4"
        metadata = cls.folder/"chapters.txt"
        metadata.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=First\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Second\n")
        subprocess.run([r.tool("ffmpeg"),"-v","error","-f","lavfi","-i","testsrc2=size=480x576:rate=25:duration=4",
                        "-f","lavfi","-i","sine=frequency=440:sample_rate=44100:duration=4","-i",str(metadata),
                        "-map","0:v","-map","1:a","-map_metadata","2","-map_chapters","2",
                        "-vf","setsar=8/5","-c:v","libx264","-preset","ultrafast","-c:a","aac",str(cls.source)],check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def export(self, name, **options):
        folder = self.folder/name; folder.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            return r.export_video(self.source,folder,dict(preset="native",enhance=False,hardware=False,**options))

    def test_native_geometry_chapters_audio_and_frame_count(self):
        result = self.export("native")
        self.assertEqual((result["width"],result["height"]),(768,576))
        self.assertEqual(result["frames"],"100")
        self.assertTrue(result["audio_bitstream_identical"])
        self.assertEqual(len(r.probe(result["file"])["chapters"]),2)

    def test_explicit_audio_and_frame_repairs(self):
        result = self.export("repairs", audio_ranges="1-1.5",hold_ranges="2-2.5")
        self.assertEqual(result["frames"],"100")
        self.assertIsNone(result["audio_bitstream_identical"])
        self.assertLess(abs(float(result["duration"])-4),.1)

    def test_1080_hevc_preview(self):
        folder = self.folder/"hevc"; folder.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            result = r.export_video(self.source,folder,dict(preset="share",enhance=False,hardware=False,preview_start="2"),preview=True)
        self.assertEqual((result["width"],result["height"]),(1920,1080))
        meta = r.probe(result["file"])
        video = next(s for s in meta["streams"] if s["codec_type"]=="video")
        self.assertEqual(video["codec_name"],"hevc")
        self.assertEqual(video["codec_tag_string"],"hvc1")
        self.assertLess(abs(float(result["duration"])-2),.15)


if __name__ == "__main__": unittest.main()
