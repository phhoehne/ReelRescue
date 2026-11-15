#!/usr/bin/env python3
"""Full-length release-engine acceptance matrix. Never modifies the input footage."""
import argparse, concurrent.futures, hashlib, itertools, json, os, plistlib, shutil, subprocess, threading, time, unicodedata
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--app',type=Path,required=True)
parser.add_argument('--report',type=Path,required=True)
parser.add_argument('--workers',type=int,default=2)
parser.add_argument('--fail-fast',action='store_true')
parser.add_argument('--keep-case', action='append', default=[], help='Keep validated video files for these IDs')
parser.add_argument('--case', action='append', default=[], help='Run only these scenario IDs (repeatable)')
parser.add_argument('--resume',action='store_true',help='Resume completed cases only when app and input hashes match')
parser.add_argument('sources',type=Path,nargs=3)
a=parser.parse_args();a.app=a.app.resolve();a.report=a.report.resolve();a.report.mkdir(parents=True,exist_ok=True)
if not a.resume and any(a.report.iterdir()):
 parser.error('Choose an empty, dedicated report directory')
if any(source.resolve().is_relative_to(a.report) for source in a.sources):
 parser.error('Input footage must be outside the report directory')

if (a.report/'summary.json').exists() and not a.resume:
 parser.error('Report directory already contains a run; choose another directory or use --resume')
engine=a.app/'Contents/Resources/runtime/engine/ReelRescueEngine'
ffmpeg=a.app/'Contents/Resources/runtime/bin/ffmpeg';probe=a.app/'Contents/Resources/runtime/bin/ffprobe'
env=dict(os.environ,PATH='/usr/bin:/bin:/usr/sbin:/sbin',PYTHONHOME='/unavailable-python',PYTHONPATH='/unavailable-python',PYINSTALLER_RESET_ENVIRONMENT='1')
lock=threading.Lock();active={};results=[];stop=threading.Event();started=time.time()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for data in iter(lambda:f.read(8*1024*1024),b''):h.update(data)
 return h.hexdigest()
def invoke(args):return subprocess.run(list(map(str,args)),env=env,text=True,capture_output=True)
def metadata(p,count=False):
 cmd=[probe,'-v','error']
 if count:cmd+=['-count_frames']
 cmd+=['-show_streams','-show_format','-of','json',p]
 r=invoke(cmd)
 if r.returncode:raise RuntimeError(r.stderr)
 return json.loads(r.stdout)
def persist():
 payload=dict(build=build,started=started,elapsed_seconds=time.time()-started,total=len(cases),passed=sum(x['status']=='passed' for x in results),failed=sum(x['status']=='failed' for x in results),active=active,results=results,inputs=inputs)
 temp=a.report/'summary.partial.json';temp.write_text(json.dumps(payload,indent=2));temp.replace(a.report/'summary.json')
print('Reading full input streams and checksums',flush=True)
inputs=[]
for p in a.sources:
 m=metadata(p,True);v=next(x for x in m['streams'] if x['codec_type']=='video')
 inputs.append(dict(path=str(p.resolve()),sha256=sha(p),frames=int(v['nb_read_frames']),duration=float(m['format']['duration']),audio_video_start_offset=float(v.get('start_time',0))-float(next(x for x in m['streams'] if x['codec_type']=='audio').get('start_time',0)),display_width=int(v['width']*(float(v.get('sample_aspect_ratio','1:1').split(':')[0])/float(v.get('sample_aspect_ratio','1:1').split(':')[-1]))//2*2),height=v['height'],interlaced=v.get('field_order') in ('tt','bb','tb','bt'),size=p.stat().st_size))
build=plistlib.loads((a.app/'Contents/Info.plist').read_bytes())['CFBundleVersion']
tool_hashes=dict(engine_sha256=sha(engine),ffmpeg_sha256=sha(ffmpeg),ffprobe_sha256=sha(probe))
names=[('Custom wedding name','Custom wedding name'),('Élodie & Dorian – final','Élodie & Dorian – final'),("Summer's memories.v2","Summer's memories.v2"),('Literal_preview','Literal_preview'),('Provided name.mp4','Provided name'),('Provided name.MOV','Provided name'),('Dollar $ and `ticks`','Dollar $ and `ticks`')]
cases=[]
def add(config,kind='export'):
 n=len(cases);name,base=names[n%len(names)]
 config=dict(mode='video',sources=[x['path'] for x in inputs],output_name=name,hardware=True,**config)
 cases.append(dict(id=f'{n+1:03d}',kind=kind,settings=config,base=base))
for combine in (False,True):add(dict(combine=combine,preset='original',container='mp4',enhance=False),kind='original')
for combined,enhance,resolution,codec,container in itertools.product((True,False),(False,True),('source','720','1080'),('h264','hevc'),('mp4','mov','mkv')):
 add(dict(combine=combined,enhance=enhance,resolution=resolution,codec=codec,container=container,preset='share' if codec=='hevc' else 'native' if resolution=='source' else 'hd'))
for combined,container,codec,resolution,audio,hold in [(True,'mp4','hevc','1080','00:10-00:10.2',''),(False,'mkv','h264','720','','00:12-00:12.2'),(True,'mov','hevc','source','00:10-00:10.2','00:12-00:12.2'),(True,'mkv','hevc','720','00:10-00:10.2','00:12-00:12.2'),(False,'mkv','hevc','source','00:10-00:10.2',''),(True,'mkv','h264','720','00:10-00:10.2','')]:
 add(dict(combine=combined,container=container,codec=codec,resolution=resolution,preset='share' if codec=='hevc' else 'hd',enhance=True,audio_ranges=audio,hold_ranges=hold),kind='repairs')
# Exercise the raw/separate, joining and repair branches before the long native
# software-encoding combinations. IDs remain stable for reports and replay.
priority=['001','002','047','079','078','080','042','018','077','076','075']
rank={case_id:index for index,case_id in enumerate(priority)}
cases.sort(key=lambda case:(rank.get(case['id'],len(rank)),case['id']))
if a.case:
 unknown=set(a.case)-{case['id'] for case in cases}
 if unknown:parser.error('Unknown scenario IDs: '+', '.join(sorted(unknown)))
 cases=[case for case in cases if case['id'] in set(a.case)]
if a.resume:
 previous=json.loads((a.report/'manifest.json').read_text())
 if previous['cases']!=cases or any(previous.get(key)!=value for key,value in tool_hashes.items()) or [(x['path'],x['sha256']) for x in previous['inputs']]!=[(x['path'],x['sha256']) for x in inputs]:
  parser.error('Cannot resume: the app engine or input footage changed')
 prior=json.loads((a.report/'summary.json').read_text())
 results=[x for x in prior['results'] if x['status']=='passed']
 completed={x['id'] for x in results}
else:completed=set()
(a.report/'manifest.json').write_text(json.dumps(dict(build=build,**tool_hashes,inputs=inputs,cases=cases),indent=2))
persist();print(f'Running {len(cases)} full-length cases with {a.workers} workers, build {build}',flush=True)

def execute(case):
 if stop.is_set() or case['id'] in completed:return
 case_id=case['id'];root=a.report/case_id
 if root.is_symlink() or root.resolve().parent!=a.report:raise RuntimeError('Unsafe test directory')
 root.mkdir(exist_ok=True);destination=root/'videos'
 if destination.is_symlink():raise RuntimeError('Output directory cannot be a symbolic link')
 if destination.exists():shutil.rmtree(destination)
 destination.mkdir()
 temp=root/'temporary';temp.mkdir(exist_ok=True);config=dict(case['settings'],destination=str(destination))
 request=root/'request.json';request.write_text(json.dumps(config,ensure_ascii=False,indent=2))
 case_env=dict(env,TMPDIR=str(temp));begin=time.time();handles={};observe_stop=threading.Event()
 def observe():
  while not observe_stop.wait(.15):
   for p in temp.rglob('*'):
    if p.is_file() and (p.suffix=='.log' or p.name.endswith('.command.json')) and p not in handles:
     try:handles[p]=p.open('rb')
     except OSError:pass
 watcher=threading.Thread(target=observe,daemon=True);watcher.start()
 complete=None;failure=None;last_saved=0
 with lock:active[case_id]=dict(settings=case['settings'],phase='Starting',fraction=None);persist()
 print('START',case_id,config.get('combine'),config.get('container'),config.get('codec'),config.get('resolution'),config.get('enhance'),flush=True)
 try:
  with (root/'events.jsonl').open('w') as events:
   child=subprocess.Popen([str(engine),'job',str(request)],env=case_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
   for line in child.stdout:
    events.write(line);events.flush()
    try:e=json.loads(line)
    except ValueError:continue
    if e.get('type')=='complete':complete=e
    if e.get('type')=='error':failure=e.get('message')
    if e.get('type')=='progress':
     with lock:
      active[case_id].update(phase=e.get('phase'),fraction=e.get('fraction'),eta_seconds=e.get('eta_seconds'),detail=e.get('detail'))
      if time.time()-last_saved>2:persist();last_saved=time.time()
   code=child.wait()
  if code or not complete:raise RuntimeError(failure or f'Engine exited {code} without a completed result')
  outputs=complete['report']['outputs'];original=case['kind']=='original'
  count=1 if config['combine'] else 3
  suffix='mpg' if original else config['container']
  expected=[f"{case['base']}{'_'+str(i+1).zfill(2) if count>1 else ''}.{suffix}" for i in range(count)]
  actual=[p.name for p in destination.iterdir()]
  norm=lambda values: sorted(unicodedata.normalize('NFC',x) for x in values)
  if norm(actual)!=norm(expected):raise AssertionError(f'Wrong output names or extra files: {actual}; expected {expected}')
  if len(outputs)!=count:raise AssertionError('Wrong output count')
  with lock:active[case_id].update(phase='Independent full-file validation',fraction=None);persist()
  checks=[]
  for i,item in enumerate(outputs):
   path=Path(item['file'])
   if path.parent!=destination or not path.is_file():raise AssertionError('Reported path is not the saved video in chosen folder')
   if sha(path)!=item['sha256']:raise AssertionError('Final saved checksum differs from the engine report')
   m=metadata(path);v=next(s for s in m['streams'] if s['codec_type']=='video');audio=[s for s in m['streams'] if s['codec_type']=='audio']
   if not audio:raise AssertionError('Audio is missing')
   if original:
    if not config['combine'] and sha(path)!=inputs[i]['sha256']:raise AssertionError('Original MPEG bytes changed')
    if config['combine'] and not item.get('payloads_identical'):raise AssertionError('Combined MPEG payload preservation was not verified')
   else:
    source_info=inputs[0] if config['combine'] else inputs[i]
    expected_size={'source':(source_info['display_width'],source_info['height']),'720':(1280,720),'1080':(1920,1080)}[config['resolution']]
    if (v['width'],v['height'])!=expected_size or v['codec_name']!=config['codec']:raise AssertionError('Wrong resolution or codec')
    if audio[0]['codec_name']!='aac':raise AssertionError('Wrong output audio codec')
    source_offset=inputs[0 if config['combine'] else i]['audio_video_start_offset']
    output_offset=float(v.get('start_time',0))-float(audio[0].get('start_time',0))
    if abs(output_offset-source_offset)>.08:raise AssertionError(f'Picture/sound start alignment changed by {output_offset-source_offset:.3f}s')
    decoding=invoke([ffmpeg,'-nostdin','-v','error','-xerror','-err_detect','explode','-threads','2','-i',path,'-map','0:v:0','-map','0:a:0?','-fps_mode','passthrough','-enc_time_base:v','demux','-progress','pipe:1','-f','null','-'])
    (root/f'decode-{i}.log').write_text(decoding.stderr)
    if decoding.returncode or decoding.stderr.strip():raise AssertionError('Independent full decode failed: '+decoding.stderr[-1500:])
    frames=int([x.split('=')[1] for x in decoding.stdout.splitlines() if x.startswith('frame=')][-1])
    expected_frames=sum(x['frames']*(2 if x['interlaced'] else 1) for x in inputs) if config['combine'] else inputs[i]['frames']*(2 if inputs[i]['interlaced'] else 1)
    if not config.get('hold_ranges') and frames!=expected_frames:raise AssertionError(f'Decoded frame count {frames} differs from expected {expected_frames}')
    expected_duration=sum(x['duration'] for x in inputs) if config['combine'] else inputs[i]['duration']
    if abs(float(m['format']['duration'])-expected_duration)>2:raise AssertionError('Unexpected final duration')
   checks.append(dict(video_start=v.get('start_time'),audio_start=audio[0].get('start_time'),hardware_encoder=item.get('hardware_encoder'),name=path.name,bytes=path.stat().st_size,duration=m['format']['duration'],video=v['codec_name'],sha256=item['sha256'],frames=item.get('frames'),audio=audio[0]['codec_name']))
  result=dict(id=case_id,status='passed',seconds=round(time.time()-begin,2),outputs=checks)
  if case_id not in a.keep_case:shutil.rmtree(destination)
 except BaseException as e:
  result=dict(id=case_id,status='failed',seconds=round(time.time()-begin,2),error=repr(e))
  if a.fail_fast:stop.set()
 finally:
  observe_stop.set();watcher.join()
  logs=root/'diagnostics';logs.mkdir(exist_ok=True)
  for p,handle in handles.items():
   try:
    handle.seek(0);target=logs/str(p.relative_to(temp)).replace('/','__');target.write_bytes(handle.read());handle.close()
   except OSError:pass
  if temp.exists():shutil.rmtree(temp)
 with lock:results.append(result);active.pop(case_id,None);persist()
 print(result['status'].upper(),case_id,result.get('error',''),round(time.time()-begin),flush=True)
 return result

with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
 list(pool.map(execute,cases))
for entry in inputs:
 if sha(Path(entry['path']))!=entry['sha256']:raise RuntimeError('Input footage changed')
if dict(engine_sha256=sha(engine),ffmpeg_sha256=sha(ffmpeg),ffprobe_sha256=sha(probe))!=tool_hashes:
 raise RuntimeError('The app or its tools changed during acceptance testing')
with lock:persist()
print('FINISHED',len(results),'cases',sum(x['status']=='failed' for x in results),'failed; input SHA-256 checksums unchanged',flush=True)
raise SystemExit(1 if any(x['status']=='failed' for x in results) or len(results)!=len(cases) else 0)
