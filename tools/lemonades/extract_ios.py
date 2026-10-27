#!/usr/bin/env python3
"""Copy a verified local iOS APFS image through a read-only macOS mount.

Never executes image content. Preserves symlinks, records hashes, detaches the
specific virtual disk returned by this invocation. Existing output is preserved.
"""
import argparse
import json
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
from fetch_ios import ROOT, LOCK, LOCK_PATH, sha_file

def selection_path(name):
    path=Path(name)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in name:
        raise ValueError('selection must be a nonempty relative path without traversal')
    return path

def copy_selection(mount,output,names):
    if not names:
        shutil.copytree(mount,output,symlinks=True)
        return
    output.mkdir()
    for name in names:
        relative=selection_path(name);source=mount/relative;target=output/relative
        if not source.parent.resolve().is_relative_to(mount.resolve()):
            raise ValueError('selection traverses a source symlink: '+name)
        target.parent.mkdir(parents=True,exist_ok=True)
        if source.is_symlink(): target.symlink_to(source.readlink())
        elif source.is_dir(): shutil.copytree(source,target,symlinks=True)
        elif source.is_file(): shutil.copy2(source,target)
        else: raise ValueError('missing/unsupported selected path: '+name)

def attached_device(data):
    entities=plistlib.loads(data)['system-entities']
    disks=[e['dev-entry'] for e in entities if re.fullmatch(r'/dev/disk\d+',e.get('dev-entry',''))]
    if not disks: raise ValueError('attach did not return a virtual disk')
    return disks[0]

def validate_mount(data,mount):
    entities=plistlib.loads(data)['system-entities']
    if not any(e.get('mount-point')==str(mount) for e in entities):
        raise ValueError('attach did not mount the requested path')

def selected_metadata(mount,names):
    """Capture original ownership before a separate noowners read-only mount."""
    if not names: raise ValueError('owner-readable mode requires explicit regular files')
    entries={}
    for name in names:
        relative=selection_path(name);source=mount/relative
        if not source.parent.resolve().is_relative_to(mount.resolve()):
            raise ValueError('selection traverses a source symlink: '+name)
        if not stat.S_ISREG(source.lstat().st_mode):
            raise ValueError('owner-readable selection must be a regular file: '+name)
        for part in [relative,*relative.parents]:
            if part==Path('.'): continue
            original=(mount/part).lstat()
            if not (stat.S_ISREG(original.st_mode) or stat.S_ISDIR(original.st_mode)):
                raise ValueError('owner-readable path has a symlink or special file')
            entries[str(part)]={'source_uid':original.st_uid,'source_gid':original.st_gid,
                'mode':stat.S_IMODE(original.st_mode),
                'type':'file' if stat.S_ISREG(original.st_mode) else 'directory',
                'source_size':original.st_size}
    return entries

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('component',choices=LOCK['components'])
    p.add_argument('--directory',type=Path,default=ROOT/'out/lemonades/ios165-source')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--include',action='append',help='copy only this relative path; repeat for a subset')
    p.add_argument('--owner-readable',action='store_true',help='regular files only: record ownership, detach, then read through a separate read-only noowners mount')
    args=p.parse_args();directory=args.directory.resolve();output=args.output.resolve()
    if not directory.is_relative_to(ROOT/'out') or not output.is_relative_to(ROOT/'out'):
        p.error('input/output directories must be under workspace out/')
    if output.exists(): p.error('output already exists; refusing overwrite')
    component=LOCK['components'][args.component];image=directory/component['name']
    record=json.loads(image.with_suffix('.json').read_text())
    if record['component']!=component or record['source_lock_sha256']!=sha_file(LOCK_PATH) or \
        image.stat().st_size!=component['size'] or sha_file(image)!=record['sha256']:
        p.error('input component failed verification')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<component['size']+(1<<30): p.error('insufficient free disk space')
    manifest=output.with_name(output.name+'-extraction.json')
    if manifest.exists(): p.error('extraction record already exists; refusing overwrite')
    entries={}
    with tempfile.TemporaryDirectory(prefix='ios-readonly-',dir=output.parent) as temporary:
        mount=Path(temporary)/'mount';mount.mkdir()
        raw=subprocess.check_output(['hdiutil','attach','-readonly','-owners','on','-nobrowse','-noautoopen','-plist',
            '-mountpoint',str(mount),str(image)])
        # Use only the freshly returned disk, never a guessed disk identifier.
        device=attached_device(raw)
        try:
            validate_mount(raw,mount)
            if args.owner_readable:
                entries=selected_metadata(mount,args.include)
            else:
                copy_selection(mount,output,args.include)
            for path in ([] if args.owner_readable else sorted(output.rglob('*'))):
                relative=str(path.relative_to(output))
                original=(mount/relative).lstat()
                entry={'source_uid':original.st_uid,'source_gid':original.st_gid,
                       'mode':stat.S_IMODE(original.st_mode)}
                if path.is_symlink(): entry.update(symlink=str(path.readlink()),type='symlink')
                elif path.is_file(): entry.update(size=path.stat().st_size,sha256=sha_file(path),type='file')
                elif path.is_dir(): entry.update(type='directory')
                else: raise ValueError('unsupported source file type: '+relative)
                entries[relative]=entry
        finally:
            subprocess.run(['hdiutil','detach',device],check=True)
        if args.owner_readable:
            raw=subprocess.check_output(['hdiutil','attach','-readonly','-owners','off','-nobrowse','-noautoopen','-plist',
                '-mountpoint',str(mount),str(image)])
            device=attached_device(raw)
            try:
                validate_mount(raw,mount)
                copy_selection(mount,output,args.include)
                for name,entry in entries.items():
                    if entry['type']=='file':
                        path=output/name
                        if path.is_symlink() or not path.is_file() or path.stat().st_size!=entry['source_size']:
                            raise ValueError('file changed between metadata/read mounts: '+name)
                        entry.update(size=path.stat().st_size,sha256=sha_file(path))
            finally:
                subprocess.run(['hdiutil','detach',device],check=True)
    manifest.write_text(json.dumps({'component':component,'image_sha256':record['sha256'],
        'source_lock_sha256':sha_file(LOCK_PATH),'read_only_mount':True,'executed_image_content':False,
        'selected_paths':args.include,'separate_owner_readable_mount':args.owner_readable,'entries':entries},indent=2)+'\n')
    print(manifest)

if __name__=='__main__': main()
