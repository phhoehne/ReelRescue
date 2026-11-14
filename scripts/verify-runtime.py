#!/usr/bin/env python3
"""Exercise a relocated app's bundled tools with Python/Homebrew paths unavailable."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    app = ROOT / 'dist/Reel Rescue.app'
    env = dict(os.environ, PATH='/usr/bin:/bin:/usr/sbin:/sbin', PYTHONHOME='/unavailable-python',
               PYTHONPATH='/unavailable-python', PYINSTALLER_RESET_ENVIRONMENT='1')
    spec = importlib.util.spec_from_file_location('rescue', ROOT/'backend/reel_rescue.py')
    rescue = importlib.util.module_from_spec(spec); spec.loader.exec_module(rescue)
    with tempfile.TemporaryDirectory(prefix='reel-relocation-') as temp:
        root = Path(temp); env['REEL_RESCUE_SUPPORT_ROOT']=str(root/'app-support'); moved = root/'Moved app/Reel Rescue.app'
        moved.parent.mkdir()
        subprocess.run(['ditto',str(app),str(moved)],check=True)
        runtime = moved/'Contents/Resources/runtime'
        engine = runtime/'engine/ReelRescueEngine'
        ffmpeg = runtime/'bin/ffmpeg'
        def run(*args):
            return subprocess.run(list(map(str,args)),env=env,text=True,capture_output=True,check=True)
        def job(settings):
            request = root/'job.json';request.write_text(json.dumps(dict(destination=str(root),**settings)))
            result=run(engine,'job',request)
            events=[json.loads(line) for line in result.stdout.splitlines()]
            assert events[-1]['type']=='complete',events[-1]
            return events[-1]['report']
        doctor = json.loads(run(engine,'doctor').stdout)
        assert doctor['checksum_accelerator']
        assert all(str(runtime) in doctor['tools'][n] for n in ('ffmpeg','ffprobe','ddrescue'))
        run(ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=480x576:rate=25:duration=3',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=3','-vf','setsar=8/5',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac',root/'input.mp4')
        native=job(dict(mode='video',sources=[str(root/'input.mp4')],preset='native',enhance=True,
                       audio_ranges='1-1.5',hold_ranges='2-2.5',hardware=False))['outputs'][0]
        assert (native['width'],native['height'],native['frames'])==(768,576,'75')
        hd=job(dict(mode='video',sources=[str(root/'input.mp4')],preset='share',enhance=False,hardware=False))['outputs'][0]
        assert (hd['width'],hd['height'])==(1920,1080)
        assert hd['audio_bitstream_identical']
        for item in (native,hd):
            project=Path(item['file']).parent
            assert {x.name for x in project.iterdir()}=={'Film.mp4'}
            assert all(p.suffix=='.mp4' for p in project.iterdir())
        # Create a raw Mode 2 image using generated MPEG payload, then recover it.
        run(ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=480x576:rate=25:duration=1',
            '-target','pal-svcd',root/'fixture.mpg')
        data=(root/'fixture.mpg').read_bytes();image=root/'fixture.bin'
        with image.open('wb') as out:
            for lba,start in enumerate(range(0,len(data),2324)):
                s=bytearray(2352);s[:12]=rescue.SYNC;n=lba+150
                for i,v in enumerate((n//4500,n//75%60,n%75),12):s[i]=(v//10)*16+v%10
                s[15]=2;s[16:20]=s[20:24]=bytes([1,0,32,0]);s[24:2348]=data[start:start+2324].ljust(2324,b'\0')
                s[2348:]=rescue.edc(bytes(s[16:2348])).to_bytes(4,'little');out.write(s)
        cue=root/'fixture.cue';cue.write_text('FILE "fixture.bin" BINARY\nTRACK 01 MODE2/2352\nINDEX 01 00:00:00\n')
        original=rescue.sha(image)
        recovered=job(dict(mode='images',sources=[str(image)],cue=str(cue),export=False))
        assert recovered['recovery']['unresolved_lbas']==[]
        project=Path(recovered['project'])
        assert {x.name for x in project.iterdir()}=={'Track_01.mpg'}
        assert Path(recovered['image']).parent.name=='Recovery data'
        assert (Path(recovered['work_directory'])/'Diagnostics/report.json').exists()
        assert Path(recovered['extracted'][0]['file']).read_bytes().startswith(data)
        assert rescue.sha(image)==original
        run(runtime/'bin/ddrescue','-q','-n','-b','2352',image,root/'copy.bin',root/'copy.map')
        assert (root/'copy.bin').read_bytes()==image.read_bytes()
        devices=json.loads(run(engine,'devices').stdout)
        # An incomplete bundle must not silently use the host's Homebrew install.
        ffmpeg.rename(ffmpeg.with_suffix('.hidden'))
        try: assert json.loads(run(engine,'doctor').stdout)['tools']['ffmpeg'] is None
        finally: ffmpeg.with_suffix('.hidden').rename(ffmpeg)
        run('codesign','--verify','--deep','--strict',moved)
        print(json.dumps(dict(relocated_bundle=True,external_tool_paths_removed=True,
            invalid_python_environment_ignored=True,native_repair_export='passed',hevc_1080p_export='passed',
            aac_audio_preserved=True,raw_image_recovery='passed',bundled_ddrescue='passed',
            missing_tool_no_host_fallback=True,code_signature='verified',detected_cd_count=len(devices['discs'])),indent=2))


if __name__=='__main__':main()
