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
    r.run([sys.executable, '-c', {('import os,time,pathlib; pathlib.Path('+repr(str(child_pid))+').write_text(str(os.getpid())); time.sleep(60)')!r}], {str(p/'child.log')!r}, 'test', read_progress=lambda:None)
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

    def test_video_publication_preserves_existing_files_and_cleans_failed_copy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/"source.mp4";src.write_bytes(b"original video");dest=p/"video.mp4"
            r.publish_video(src,dest);self.assertEqual(dest.read_bytes(),src.read_bytes())
            with self.assertRaises(r.RescueError):r.publish_video(src,dest)
            self.assertEqual(src.read_bytes(),b"original video")
            dest.unlink()
            partial=p/".video.partial.mp4";partial.write_bytes(b"existing file")
            with self.assertRaises(FileExistsError):r.publish_video(src,dest)
            self.assertEqual(partial.read_bytes(),b"existing file")
            partial.unlink()
            with patch.object(r.shutil,"copyfileobj",side_effect=r.Cancelled):
                with self.assertRaises(r.Cancelled):r.publish_video(src,dest)
            self.assertFalse(partial.exists());self.assertFalse(dest.exists())

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

    def test_job_publishes_only_video_and_discards_temporary_files(self):
        parent=self.folder/"scratch";parent.mkdir()
        with patch.object(r.tempfile,"tempdir",str(parent)), contextlib.redirect_stdout(io.StringIO()) as output:
            r.job(dict(mode="video",sources=[str(self.source)],destination=str(self.folder),preset="native",enhance=False,hardware=False))
        event=json.loads(output.getvalue().splitlines()[-1]);p=Path(event["project"])
        self.assertEqual({x.name for x in p.iterdir()},{"Film.mp4"})
        self.assertEqual(list(parent.iterdir()),[])
        self.assertNotIn("details",event)
        self.assertEqual(event["report"]["layout_version"],4)
        self.assertTrue(event["report"]["outputs"][0]["audio_bitstream_identical"])

    def test_failed_recovery_discards_working_files_and_preserves_source(self):
        source=self.folder/"bad-image.bin";source.write_bytes(b"unreadable source")
        parent=self.folder/"failure-scratch";parent.mkdir()
        with patch.object(r.tempfile,"tempdir",str(parent)), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(r.RescueError):
                r.job(dict(mode="images",sources=[str(source)],destination=str(self.folder)))
        event=json.loads(output.getvalue().splitlines()[0]);p=Path(event["path"])
        self.assertEqual(list(parent.iterdir()),[])
        self.assertEqual(list(p.iterdir()),[])
        self.assertEqual(source.read_bytes(),b"unreadable source")

    def test_cancelled_recovery_removes_all_temporary_work(self):
        parent=self.folder/"cancelled-scratch";parent.mkdir()
        with patch.object(r.tempfile,"tempdir",str(parent)), patch.object(r,"merge_images",side_effect=r.Cancelled), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(r.Cancelled):
                r.job(dict(mode="images",sources=[str(self.source)],destination=str(self.folder)))
        event=json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(list(Path(event["path"]).iterdir()),[])
        self.assertEqual(list(parent.iterdir()),[])
        self.assertTrue(self.source.exists())

    def test_combine_mpeg_tracks_without_reencoding(self):
        folder=self.folder/"combine";folder.mkdir();sources=[]
        for index in range(2):
            path=folder/f"source{index}.mpg"
            subprocess.run([r.tool("ffmpeg"),"-v","error","-f","lavfi","-i","testsrc2=size=480x576:rate=25:duration=1", "-f","lavfi","-i","sine=frequency=440:duration=1", "-target","pal-svcd","-t","1",str(path)],check=True)
            sources.append(str(path))
        with contextlib.redirect_stdout(io.StringIO()):record=r.combine_tracks(sources,folder)
        self.assertTrue(record["stream_copy"])
        self.assertEqual(r.decoded_frames(record["file"]),50)
        def audio_payload(path):
            return subprocess.check_output([r.tool("ffmpeg"),"-v","error","-i",str(path),"-map","0:a:0","-c","copy","-f","data","-"],stderr=subprocess.DEVNULL)
        self.assertEqual(audio_payload(record["file"]),b"".join(audio_payload(path) for path in sources))
        self.assertEqual(next(s for s in r.probe(record["file"])["streams"] if s["codec_type"]=="video")["codec_name"],"mpeg2video")

    def test_combine_repairs_corrupt_pes_timestamps_without_changing_streams(self):
        folder=self.folder/"corrupt-join";folder.mkdir()
        first=folder/"first.mpg";second=folder/"second.mpg"
        for path,length in [(first,8),(second,1)]:
            subprocess.run([r.tool("ffmpeg"),"-v","error","-f","lavfi","-i",f"testsrc2=size=480x576:rate=25:duration={length}",
                "-f","lavfi","-i",f"sine=frequency=440:duration={length}","-target","pal-svcd","-t",str(length),str(path)],check=True)
        data=bytearray(first.read_bytes());positions=[];position=0
        while True:
            position=data.find(b"\0\0\1\xe0",position)
            if position<0:break
            if position+19<len(data) and data[position+7]&0xC0==0xC0:positions.append(position)
            position+=4
        self.assertTrue(positions)
        position=positions[len(positions)//2]
        # Change only the PES timestamps, leaving compressed video/audio intact.
        # Include the second failure mode: PTS jumps while DTS stays valid.
        pts_only=positions[len(positions)//3]
        for offset in (position+9,position+14,pts_only+9):
            b=data[offset:offset+5]
            stamp=((b[0]>>1)&7)<<30 | (((b[1]<<8)|b[2])>>1)<<15 | (((b[3]<<8)|b[4])>>1)
            stamp=(stamp+3600*90000)%(1<<33)
            data[offset:offset+5]=bytes([(b[0]&0xF0)|(((stamp>>30)&7)<<1)|1,(stamp>>22)&255,((stamp>>15)&127)<<1|1,(stamp>>7)&255,(stamp&127)<<1|1])
        first.write_bytes(data);before=[r.sha(path) for path in (first,second)]
        with contextlib.redirect_stdout(io.StringIO()):record=r.combine_tracks([first,second],folder)
        self.assertTrue(record["timestamps_normalized"])
        self.assertTrue(record["payloads_identical"])
        self.assertEqual(record["frames"],225)
        self.assertLess(abs(float(r.probe(record["file"])["format"]["duration"])-9),0.5)
        self.assertEqual([r.sha(path) for path in (first,second)],before)

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
