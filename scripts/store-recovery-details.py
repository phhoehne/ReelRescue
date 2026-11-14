#!/usr/bin/env python3
"""Move technical files from a completed output into app-managed support storage."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def store(folder, support=None):
    folder=Path(folder).expanduser().resolve()
    report_path=folder/'Diagnostics/report.json'
    report=json.loads(report_path.read_text())
    if report.get('status')!='complete':raise RuntimeError('Only completed recoveries can be moved.')
    support=Path(support).expanduser().resolve() if support else Path.home()/'Library/Application Support/Reel Rescue/Projects'
    work=support/folder.name
    if work.exists():raise RuntimeError('Recovery details already exist; refusing to overwrite.')
    allowed={'Diagnostics','Recovery data','Results.txt'}
    for item in folder.iterdir():
        if item.is_symlink():raise RuntimeError('Inspect project symlinks before moving details.')
        if item.name not in allowed and (not item.is_file() or item.suffix.lower() not in ('.mp4','.m4v','.mov','.mpg','.mpeg')):
            raise RuntimeError(f'Unexpected output item: {item.name}; nothing moved.')
    if any(p.is_symlink() for p in folder.rglob('*')):raise RuntimeError('Inspect nested symlinks before moving details.')
    originals={str(p):sha(p) for p in folder.rglob('*') if p.is_file()}
    mapping={str(p):str(work/p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and p.relative_to(folder).parts[0] in allowed}
    def update(value):
        if isinstance(value,str):
            canonical=str(Path(value).resolve()) if value.startswith('/') else value
            return mapping.get(value,mapping.get(canonical,value))
        if isinstance(value,list):return [update(v) for v in value]
        if isinstance(value,dict):return {k:update(v) for k,v in value.items()}
        return value
    work.mkdir(parents=True)
    if folder.stat().st_dev!=work.stat().st_dev:
        work.rmdir();raise RuntimeError('Cross-volume storage migration requires a separate verified copy; nothing moved.')
    for name in allowed:
        if (folder/name).exists():(folder/name).rename(work/name)
    backup=work/'Diagnostics/Before storage move'
    for old,new in mapping.items():
        path=Path(new)
        if path.suffix!='.json' or 'Original records' in path.parts:continue
        raw=path.read_bytes();record=update(json.loads(raw))
        if path==work/'Diagnostics/report.json':record.update(layout_version=3,work_directory=str(work))
        if record!=json.loads(raw):
            saved=backup/path.relative_to(work);saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(raw)
            path.write_text(json.dumps(record,indent=2)+'\n')
    checksum=work/'Diagnostics/SHA256SUMS.txt'
    if checksum.exists():
        saved=backup/'Diagnostics/SHA256SUMS.txt';saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(checksum.read_bytes())
        current_report=json.loads((work/'Diagnostics/report.json').read_text())
        checksum.write_text(''.join(item['sha256']+'  '+item['file']+'\n' for item in current_report.get('outputs',[]) if item.get('sha256')))
    for old,digest in originals.items():
        current=Path(mapping.get(old,old))
        if sha(current)!=digest:
            saved=backup/current.relative_to(work)
            if not saved.exists() or sha(saved)!=digest:raise RuntimeError(f'Original verification failed: {old}')
    (work/'Diagnostics/Storage migration.json').write_text(json.dumps(dict(output=str(folder),work_directory=str(work),mapping=mapping,sha256_before=originals,all_original_files_preserved=True),indent=2)+'\n')
    return dict(output=str(folder),recovery_details=str(work),all_original_files_preserved=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder');args=parser.parse_args()
    print(json.dumps(store(args.folder),indent=2))
