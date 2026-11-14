#!/usr/bin/env python3
"""Organize a completed legacy recovery without deleting any existing files."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()


def organize(folder):
    folder=Path(folder).expanduser().resolve()
    old_report=folder/'report.json'
    if not old_report.exists():
        raise RuntimeError('Expected an unorganized legacy project with report.json at its root.')
    report=json.loads(old_report.read_text())
    if report.get('status')!='complete':
        raise RuntimeError('Only completed projects can be organized. Active and partial recoveries are left untouched.')
    data=folder/'Recovery data';diag=folder/'Diagnostics';originals=diag/'Original records'
    if data.exists() or diag.exists(): raise RuntimeError('Destination folders already exist; refusing to merge or overwrite.')
    moves=[]
    for item in folder.iterdir():
        if item.is_symlink(): raise RuntimeError('Project contains a symlink; inspect it manually before organizing.')
        if item.name=='Original MPEG streams' and item.is_dir():
            moves.append((item,data/'Original video'))
        elif item.is_file() and item.suffix.lower() in ('.bin','.map','.cue'):
            moves.append((item,data/item.name))
        elif item.is_file() and (item.suffix.lower() in ('.json','.log') or item.name in ('READ ME.txt','SHA256SUMS.txt')):
            moves.append((item,diag/item.name))
    mapping={}
    for old,new in moves:
        if old.is_dir():
            for file in old.rglob('*'):
                if file.is_symlink(): raise RuntimeError('Recovery data contains a symlink; refusing migration.')
                if file.is_file(): mapping[str(file)]=str(new/file.relative_to(old))
        else: mapping[str(old)]=str(new)
    all_files=[f for f in folder.rglob('*') if f.is_file()]
    fingerprints={str(f):sha(f) for f in all_files}
    def update(value):
        if isinstance(value,str):
            canonical = str(Path(value).resolve()) if value.startswith('/') else value
            return mapping.get(value,mapping.get(canonical,value))
        if isinstance(value,list): return [update(v) for v in value]
        if isinstance(value,dict): return {k:update(v) for k,v in value.items()}
        return value
    data.mkdir();diag.mkdir();originals.mkdir()
    journal=dict(status='moving',mapping=mapping,sha256_before=fingerprints)
    journal_path=diag/'organization.json'
    journal_path.write_text(json.dumps(journal,indent=2)+'\n')
    for old,new in moves: old.rename(new)
    # Keep original records byte-for-byte, then update current path references.
    for old,new in mapping.items():
        path=Path(new)
        if path.suffix=='.json':
            raw=path.read_bytes()
            updated=update(json.loads(raw))
            if path.name=='report.json': updated['layout_version']=2
            if updated!=json.loads(raw):
                backup=originals/path.name
                backup.write_bytes(raw)
                path.write_text(json.dumps(updated,indent=2)+'\n')
    report=json.loads((diag/'report.json').read_text())
    spec=importlib.util.spec_from_file_location('rescue',ROOT/'backend/reel_rescue.py')
    rescue=importlib.util.module_from_spec(spec);spec.loader.exec_module(rescue)
    rescue.write_summary(folder,report)
    checksum=diag/'SHA256SUMS.txt'
    if checksum.exists(): shutil.copy2(checksum,originals/checksum.name)
    checksum.write_text(''.join(item['sha256']+'  ../'+Path(item['file']).name+'\n' for item in report.get('outputs',[])))
    # Every original file must be retained, either at its mapped location or as
    # a byte-identical original record if its current JSON path references changed.
    for old,digest in fingerprints.items():
        current=Path(mapping.get(old,old))
        if sha(current)!=digest:
            backup=originals/current.name
            if not backup.exists() or sha(backup)!=digest:
                raise RuntimeError(f'Original-content verification failed: {old}')
    journal.update(status='complete',all_original_files_preserved=True)
    journal_path.write_text(json.dumps(journal,indent=2)+'\n')
    return dict(project=str(folder),original_files=len(fingerprints),all_original_files_preserved=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('project');args=parser.parse_args()
    print(json.dumps(organize(args.project),indent=2))
