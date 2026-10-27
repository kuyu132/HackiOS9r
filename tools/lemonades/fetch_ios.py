#!/usr/bin/env python3
"""Read pinned Apple IPSW metadata, optionally stream one allowlisted component.

Local output only. Validates HTTPS ranges/ETag, pinned BuildManifest SHA-256,
version, identity/component path, ZIP sizes and CRC. Does NOT verify Apple image
signatures or prove hardware compatibility. No extract-all, restore or device I/O.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[2]
LOCK_PATH=Path(__file__).with_name('ios165-source-lock.json')
LOCK=json.loads(LOCK_PATH.read_text())
spec=importlib.util.spec_from_file_location('stock_range',Path(__file__).with_name('fetch-stock.py'))
stock=importlib.util.module_from_spec(spec)
spec.loader.exec_module(stock)

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1<<20): h.update(block)
    return h.hexdigest()

def validate_manifest(raw,lock=LOCK):
    if hashlib.sha256(raw).hexdigest()!=lock['build_manifest_sha256']:
        raise ValueError('BuildManifest SHA-256 mismatch')
    manifest=plistlib.loads(raw)
    if manifest.get('ProductVersion')!=lock['product_version'] or manifest.get('ProductBuildVersion')!=lock['build']:
        raise ValueError('iOS build/version mismatch')
    if set(manifest.get('SupportedProductTypes',[]))!=set(lock['supported_product_types']):
        raise ValueError('product types mismatch')
    matches=[i for i in manifest['BuildIdentities'] if i['Info'].get('DeviceClass')==lock['device_class']
             and i['Info'].get('RestoreBehavior')=='Erase']
    if len(matches)!=1: raise ValueError('ambiguous/missing source identity')
    for component in lock['components'].values():
        if matches[0]['Manifest'][component['manifest_key']]['Info']['Path']!=component['name']:
            raise ValueError('component path mismatch')
    return matches[0]['Info']

def validate_member(info,component):
    if info.filename!=component['name'] or '/' in info.filename or '\\' in info.filename:
        raise ValueError('unexpected ZIP member name')
    if (info.file_size,info.compress_size,info.CRC)!=(component['size'],component['compressed_size'],int(component['crc32'],16)):
        raise ValueError('ZIP member size/CRC changed')
    if info.flag_bits&1 or info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
        raise ValueError('encrypted/unsupported ZIP method')

def download(archive,component,output):
    info=archive.getinfo(component['name']);validate_member(info,component)
    target=output/component['name']; record=target.with_suffix('.json')
    if target.exists() or record.exists():
        if not target.is_file() or not record.is_file(): raise ValueError('incomplete existing component; refusing overwrite')
        saved=json.loads(record.read_text())
        if saved.get('component')!=component or saved.get('source_lock_sha256')!=sha_file(LOCK_PATH) or \
            target.stat().st_size!=component['size'] or sha_file(target)!=saved.get('sha256'):
            raise ValueError('existing component failed verification; refusing overwrite')
        return saved
    if shutil.disk_usage(output).free<component['size']+(1<<30): raise ValueError('insufficient free disk space')
    partial=target.with_suffix('.dmg.partial')
    digest=hashlib.sha256(); count=0
    # Exclusive creation: never truncate unrelated or earlier partial output.
    with partial.open('xb') as destination:
        try:
            with archive.open(info) as stream:
                while block:=stream.read(1<<20):
                    count+=len(block)
                    if count>component['size']: raise ValueError('component exceeds pinned size')
                    destination.write(block);digest.update(block)
                    if count%(64<<20)==0: print(f'{component["name"]}: {count}/{component["size"]}',flush=True)
            if count!=component['size']: raise ValueError('truncated component')
        except BaseException:
            # This call created the partial. Completed/other files remain intact.
            partial.unlink(missing_ok=True)
            raise
    saved={'component':component,'sha256':digest.hexdigest(),'source_lock_sha256':sha_file(LOCK_PATH),
           'zip_crc_verified':True,'apple_image_signature_verified':False}
    partial.rename(target)
    record.write_text(json.dumps(saved,indent=2)+'\n')
    return saved

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=LOCK['components'],help='omit to verify metadata only')
    parser.add_argument('--output',type=Path,default=ROOT/'out/lemonades/ios165-source')
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'out'): parser.error('output must be under workspace out/')
    output.mkdir(parents=True,exist_ok=True)
    remote=stock.RemoteZip(LOCK['url'])
    if remote.size!=LOCK['size']: raise ValueError('IPSW size changed')
    with zipfile.ZipFile(remote) as archive:
        if len(archive.namelist())!=len(set(archive.namelist())): raise ValueError('duplicate ZIP members')
        info=archive.getinfo('BuildManifest.plist')
        if info.file_size>16<<20: raise ValueError('oversized BuildManifest')
        raw=archive.read(info);identity=validate_manifest(raw)
        for component in LOCK['components'].values(): validate_member(archive.getinfo(component['name']),component)
        manifest_path=output/'BuildManifest.plist'
        if manifest_path.exists() and manifest_path.read_bytes()!=raw: raise ValueError('existing manifest differs')
        manifest_path.write_bytes(raw)
        report={'source_lock_sha256':sha_file(LOCK_PATH),'url':LOCK['url'],'etag':remote.etag,
                'size':remote.size,'identity':identity,'build_manifest_sha256':hashlib.sha256(raw).hexdigest()}
        if args.component:
            # Larger bounded range cache for sequential ZIP decompression.
            remote.cache.clear();remote.chunk_size=8<<20
            report['download']=download(archive,LOCK['components'][args.component],output)
        report['network_bytes']=remote.downloaded
        report_path=output/('fetch-'+(args.component or 'metadata')+'.json')
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(report_path,flush=True)

if __name__=='__main__': main()
