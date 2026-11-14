import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('organizer',ROOT/'scripts/organize-project.py')
organizer=importlib.util.module_from_spec(spec);spec.loader.exec_module(organizer)


class OrganizationTests(unittest.TestCase):
    def test_legacy_files_preserved_and_internal_references_updated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'Original MPEG streams').mkdir()
            original=p/'Original MPEG streams/Track_01.mpg';original.write_bytes(b'precious original')
            video=p/'Track_01.mp4';video.write_bytes(b'playable video')
            image=p/'recovered.bin';image.write_bytes(b'raw image')
            report=dict(status='complete',mode='images',outputs=[dict(file=str(video),source=str(original),sha256=organizer.sha(video))],extracted=[dict(file=str(original))],image=str(image))
            before=json.dumps(report);(p/'report.json').write_text(before)
            (p/'settings.json').write_text('{}');(p/'SHA256SUMS.txt').write_text('old checksums')
            result=organizer.organize(p)
            self.assertTrue(result['all_original_files_preserved'])
            self.assertEqual(video.read_bytes(),b'playable video')
            self.assertEqual((p/'Recovery data/Original video/Track_01.mpg').read_bytes(),b'precious original')
            current=json.loads((p/'Diagnostics/report.json').read_text())
            self.assertEqual(current['image'],str(p.resolve()/'Recovery data/recovered.bin'))
            self.assertEqual((p/'Diagnostics/Original records/report.json').read_text(),before)
            self.assertEqual({x.name for x in p.iterdir()},{'Track_01.mp4','Results.txt','Recovery data','Diagnostics'})
            with self.assertRaises(RuntimeError):organizer.organize(p)

    def test_active_recovery_is_not_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'report.json').write_text('{"status":"running"}')
            with self.assertRaises(RuntimeError):organizer.organize(p)
            self.assertEqual({x.name for x in p.iterdir()},{'report.json'})
