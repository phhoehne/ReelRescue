import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('progress_engine',ROOT/'backend/reel_rescue.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class CDProgressTests(unittest.TestCase):
    def test_partial_or_overlapping_map_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'disc.map'
            for data in ['0 20 +\n','0 60 +\n50 50 ?\n','0 20 +\n40 60 ?\n']:
                p.write_text(data)
                self.assertIsNone(r.rescued_bytes(p,100))
            p.write_text('# current_pos current_status current_pass\n0x20 ? 1\n0x00 0x14 +\n0x14 0x14 *\n0x28 0x3c ?\n')
            self.assertEqual(r.rescued_bytes(p,100),20)

    def test_raw_device_map_with_unbounded_tail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'disc.map'
            p.write_text('# current_pos current_status current_pass\n0x00107910 ? 1\n'
                         '0x00000000 0x00117120 +\n0x00117120 0x022CC6E0 ?\n'
                         '0x023E3800 0x7FFFFFFFFDC1C7FF ?\n')
            self.assertEqual(r.rescued_bytes(p,37632000),0x00117120)
            # One map interval can cross the domain boundary as well.
            p.write_text('0 20 +\n20 0x7FFFFFFFFFFFFFEB ?\n')
            self.assertEqual(r.rescued_bytes(p,100),20)

    def test_eta_tracks_progress_and_disappears_when_stalled(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'disc.map';clock=[0.0]
            tracker=r.CDReadProgress(p,100,clock=lambda:clock[0])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                tracker()
                p.write_text('0 20 +\n20 80 ?\n');clock[0]=2;tracker()
                p.write_text('0 40 +\n40 60 ?\n');clock[0]=3;tracker()
                clock[0]=9;tracker()
                # A transient truncated map must not reset visible progress.
                p.write_text('0 10 +\n');clock[0]=10;tracker()
            events=[json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(events[0]['fraction'],0)
            self.assertEqual(events[1]['fraction'],0.2)
            self.assertAlmostEqual(events[1]['eta_seconds'],8)
            self.assertEqual(events[2]['fraction'],0.4)
            self.assertIsNone(events[3]['eta_seconds'])
            self.assertIn('Waiting for drive',events[3]['detail'])
            self.assertEqual(events[4]['fraction'],0.4)

    @unittest.skipUnless(r.tool('ddrescue',False),'ddrescue required')
    def test_actual_ddrescue_emits_progress_during_a_throttled_read(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);source=p/'source.bin';source.write_bytes(b'A'*(2352*500));size=2352*400
            original=r.sha(source)
            tracker=r.CDReadProgress(p/'disc.map',size)
            command=[r.tool('ddrescue'),'-q','-n','--mapfile-interval=1,5','--max-read-rate=235200',
                     '-b','2352','-s',str(size),str(source),str(p/'copy.bin'),str(p/'disc.map')]
            with contextlib.redirect_stdout(io.StringIO()) as out:
                r.run(command,p/'capture.log','Reading the CD',read_progress=tracker)
            events=[json.loads(line) for line in out.getvalue().splitlines()]
            self.assertTrue(any(0<e['fraction']<1 for e in events),events)
            self.assertTrue(any(e.get('eta_seconds') is not None for e in events),events)
            self.assertEqual(events[-1]['fraction'],1)
            self.assertEqual(r.sha(source),original)
            self.assertEqual((p/'copy.bin').read_bytes(),source.read_bytes()[:size])


if __name__=='__main__':unittest.main()
