#!/usr/bin/env python3
"""Check output-name protection and cancellation using three real MPEG inputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app', type=Path, default=ROOT/'dist/Reel Rescue.app')
parser.add_argument('sources', type=Path, nargs=3)
args = parser.parse_args()
engine = args.app.resolve()/'Contents/Resources/runtime/engine/ReelRescueEngine'
if any(not source.is_file() for source in args.sources):
    parser.error('Choose three existing MPEG files')
with tempfile.TemporaryDirectory(prefix='ReelOutputSafety-') as directory:
    root = Path(directory)
    output = root/'Videos with spaces'; output.mkdir()
    temporary = root/'temporary'; temporary.mkdir()
    request = root/'request.json'
    environment = dict(os.environ, TMPDIR=str(temporary), PATH='/usr/bin:/bin:/usr/sbin:/sbin',
                       PYTHONHOME='/unavailable-python', PYTHONPATH='/unavailable-python')
    settings = dict(mode='video', sources=[str(p.resolve()) for p in args.sources],
                    preset='original', combine=False, destination=str(output), output_name='User chosen name')
    def run(config):
        request.write_text(json.dumps(config))
        return subprocess.run([str(engine),'job',str(request)],env=environment,text=True,capture_output=True)
    sentinel = output/'User chosen name_01.mpg'
    sentinel.write_bytes(b'EXISTING VIDEO MUST SURVIVE')
    result = run(settings)
    assert result.returncode and 'already exists' in result.stdout, result.stdout
    assert sentinel.read_bytes() == b'EXISTING VIDEO MUST SURVIVE'
    assert list(output.iterdir()) == [sentinel]
    sentinel.unlink()
    print('PASS existing-name collision preserves the file and creates no other outputs',flush=True)
    for name in ('../outside','bad:name','','..','bad\\name'):
        result = run(dict(settings,output_name=name))
        assert result.returncode and not list(output.iterdir()), result.stdout
    print('PASS invalid names do not create files or silently use a default name',flush=True)
    request.write_text(json.dumps(dict(settings,combine=True,preset='share',codec='hevc',
                                      resolution='1080',container='mp4')))
    child = subprocess.Popen([str(engine),'job',str(request)],env=environment,text=True,
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    lines = []
    try:
        for line in child.stdout:
            lines.append(line)
            if 'Preparing track' in line:
                child.terminate()
                break
        tail = child.communicate(timeout=30)[0]
    finally:
        if child.poll() is None:
            child.terminate(); child.wait(timeout=30)
    message = ''.join(lines)+tail
    assert child.returncode == 130 and 'cancelled' in message, message
    assert not list(output.iterdir()) and not list(temporary.iterdir())
    print('PASS cancellation leaves no unfinished output or temporary work',flush=True)
    protected = root/'Read only destination'; protected.mkdir(); protected.chmod(0o555)
    try:
        result = run(dict(settings,destination=str(protected)))
        assert result.returncode and not list(protected.iterdir()), result.stdout
    finally:
        protected.chmod(0o755)
    print('PASS an unwritable destination fails without publishing files',flush=True)
