#!/usr/bin/env python3
"""Selectively extract full-OTA partitions over HTTPS, verifying manifest hashes.

No device access. Does not authenticate the OTA signing certificate or verify the
whole ZIP/payload hash (unrequested bytes are not downloaded). See firmware report.
"""
import argparse
import base64
import bz2
from collections import OrderedDict
import hashlib
import http.client
import io
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_COMMIT = 'c3a50ba8d784764c06143c1f82971cd81a77f9d6'
URL = ('https://gauss-componentotamanual.allawnofs.com/'
       'remove-566192819778b5d05fe940821765358d/component-ota/25/08/16/'
       'b3fc45995d0f4291aa3d9761365d51fc.zip')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        if not url.startswith('https://'):
            raise ValueError('HTTPS URL required')
        self.url, self.pos, self.size, self.etag = url, 0, None, None
        self.downloaded = 0
        self.cache = OrderedDict()
        self.chunk_size = 65536
        self.fetch(0, 1)

    def fetch(self, start, size):
        headers = {'Range': f'bytes={start}-{start + size - 1}',
                   'Accept-Encoding': 'identity', 'User-Agent': 'HackiOS9R-offline-research/1'}
        if self.etag:
            headers['If-Match'] = self.etag
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(self.url, headers=headers), timeout=30) as r:
                    expected = f'bytes {start}-{start + size - 1}/'
                    cr = r.headers.get('Content-Range', '')
                    if r.status != 206 or not cr.startswith(expected):
                        raise ValueError(f'invalid Range response: {r.status}, {cr}')
                    total, etag = int(cr.split('/')[1]), r.headers.get('ETag')
                    if not etag or (self.size is not None and (total != self.size or etag != self.etag)):
                        raise ValueError('remote object changed or has no ETag')
                    data = r.read(size + 1)
                    if len(data) < size:
                        raise EOFError('short Range response')
                    if len(data) > size:
                        raise ValueError('oversized Range response')
                    self.size, self.etag = total, etag
                    self.downloaded += len(data)
                    return data
            except (OSError, TimeoutError, EOFError, http.client.IncompleteRead):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        new = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        if new < 0 or new > self.size or whence not in (0, 1, 2):
            raise ValueError('invalid seek')
        self.pos = new
        return new

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else min(size, self.size - self.pos)
        if size > 64 * 1024 * 1024:
            raise ValueError('unbounded remote read refused')
        pieces = []
        while size:
            start = self.pos // self.chunk_size * self.chunk_size
            key = (start, self.chunk_size)
            if key not in self.cache:
                self.cache[key] = self.fetch(start, min(self.chunk_size, self.size - start))
                if len(self.cache) > 16:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            chunk = self.cache[key]
            offset = self.pos - start
            n = min(size, len(chunk) - offset)
            pieces.append(chunk[offset:offset + n])
            self.pos += n
            size -= n
        return b''.join(pieces)

    def at(self, offset, size):
        self.seek(offset)
        data = self.read(size)
        if len(data) != size:
            raise ValueError('range outside object')
        return data


def unpack_operation(kind, data, size):
    if size > 64 * 1024 * 1024:
        raise ValueError('operation exceeds memory bound')
    if kind == 0:
        result = data
    elif kind in (1, 8):
        decoder = bz2.BZ2Decompressor() if kind == 1 else lzma.LZMADecompressor()
        result = decoder.decompress(data, max_length=size + 1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError('compressed operation incomplete or has trailing bytes')
    elif kind == 6 and not data:
        result = bytes(size)
    else:
        raise ValueError(f'unsupported operation {kind}; incremental payloads are not supported')
    if len(result) != size:
        raise ValueError('operation output length mismatch')
    return result


def extract_partition(remote, data_base, data_end, part, block, out):
    name, size = part.partition_name, part.new_partition_info.size
    expected = part.new_partition_info.hash.hex()
    if not re.fullmatch(r'[a-z0-9_]+', name) or not 0 < size <= 256 * 1024 * 1024 or len(expected) != 64:
        raise ValueError('partition name, size or hash invalid')
    if part.HasField('old_partition_info'):
        raise ValueError(f'{name}: incremental partition refused')
    target = out / f'{name}.img'
    if target.exists():
        if target.stat().st_size != size or sha(target.read_bytes()) != expected:
            raise ValueError(f'{target}: existing file differs; refusing overwrite')
        return {'name': name, 'size': size, 'sha256': expected, 'manifest_hash_verified': True, 'reused': True}
    temporary = target.with_suffix('.img.partial')
    intervals = []
    with temporary.open('wb') as f:
        f.truncate(size)
        for op in part.operations:
            if op.src_extents or op.type not in (0, 1, 6, 8):
                raise ValueError(f'{name}: unsupported/source-dependent operation {op.type}')
            extents = [(e.start_block * block, e.num_blocks * block) for e in op.dst_extents]
            if not extents or any(n == 0 or start + n > size for start, n in extents):
                raise ValueError('destination extent outside partition')
            intervals.extend(extents)
            if op.data_length > 64 * 1024 * 1024 or data_base + op.data_offset + op.data_length > data_end:
                raise ValueError('operation data outside payload')
            encoded = remote.at(data_base + op.data_offset, op.data_length) if op.data_length else b''
            if encoded and hashlib.sha256(encoded).digest() != op.data_sha256_hash:
                raise ValueError(f'{name}: operation SHA-256 mismatch')
            decoded = unpack_operation(op.type, encoded, sum(n for _, n in extents))
            cursor = 0
            for start, n in extents:
                f.seek(start)
                f.write(decoded[cursor:cursor + n])
                cursor += n
    cursor = 0
    for start, length in sorted(intervals):
        if start != cursor:
            raise ValueError('partition extents overlap or leave gaps')
        cursor += length
    if cursor != size or sha(temporary.read_bytes()) != expected:
        raise ValueError(f'{name}: final image SHA-256/size mismatch')
    temporary.rename(target)
    return {'name': name, 'size': size, 'sha256': expected, 'manifest_hash_verified': True, 'reused': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--url', default=URL)
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/stock/LE2101_14.0.0.2301')
    ap.add_argument('--partitions', default='', help='comma-separated; empty lists payload only')
    ap.add_argument('--expected-version', default='LE2101_14.0.0.2301(EX01)')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    schema = subprocess.check_output(['git', '-C', str(ROOT / 'sources/payload-dumper-go'),
                                      'show', SCHEMA_COMMIT + ':update_metadata.proto'])
    generated = out / 'schema'
    generated.mkdir(exist_ok=True)
    (generated / 'update_metadata.proto').write_bytes(schema)
    subprocess.run([sys.executable, '-m', 'grpc_tools.protoc', f'-I{generated}',
                    f'--python_out={generated}', str(generated / 'update_metadata.proto')], check=True)
    sys.path.insert(0, str(generated))
    from update_metadata_pb2 import DeltaArchiveManifest
    remote = RemoteZip(args.url)
    archive = zipfile.ZipFile(remote)
    for name in ['META-INF/com/android/metadata', 'payload_properties.txt']:
        if archive.getinfo(name).file_size > 1024 * 1024:
            raise ValueError('oversized OTA metadata')
        data = archive.read(name)  # zipfile validates the CRC of these complete entries
        (out / Path(name).name).write_bytes(data)
    metadata = (out / 'metadata').read_text()
    print(metadata, flush=True)
    metadata_fields = dict(line.split('=', 1) for line in metadata.splitlines() if '=' in line)
    if (metadata_fields.get('pre-device') != 'OnePlus9R' or
            metadata_fields.get('version_name') != args.expected_version):
        raise ValueError('package metadata does not match OnePlus9R / expected version')
    props = dict(line.split('=', 1) for line in (out / 'payload_properties.txt').read_text().splitlines() if '=' in line)
    entry = archive.getinfo('payload.bin')
    if entry.compress_type != zipfile.ZIP_STORED or entry.flag_bits & 1:
        raise ValueError('expected unencrypted stored payload.bin')
    local = remote.at(entry.header_offset, 30)
    if local[:4] != b'PK\x03\x04':
        raise ValueError('bad local ZIP header')
    name_size, extra_size = struct.unpack_from('<HH', local, 26)
    offset = entry.header_offset + 30 + name_size + extra_size
    magic, version, manifest_size, signature_size = struct.unpack('>4sQQI', remote.at(offset, 24))
    if magic != b'CrAU' or version != 2 or manifest_size > 32 * 1024 * 1024 or signature_size > 1024 * 1024:
        raise ValueError('unsupported payload header')
    metadata_size = 24 + manifest_size + signature_size
    header = remote.at(offset, metadata_size)
    # payload_properties hashes header + manifest, excluding the following signature.
    if (int(props['METADATA_SIZE']) != 24 + manifest_size or int(props['FILE_SIZE']) != entry.file_size or
            hashlib.sha256(header[:24 + manifest_size]).digest() != base64.b64decode(props['METADATA_HASH'])):
        raise ValueError('payload metadata hash/size mismatch')
    if args.url == URL:
        pin = json.loads(Path(__file__).with_name('firmware-sources.json').read_text())
        if sha(header[:24 + manifest_size]) != pin['properties_metadata_sha256']:
            raise ValueError('default package metadata differs from reviewed download')
    (out / 'payload-metadata.bin').write_bytes(header)
    manifest = DeltaArchiveManifest.FromString(header[24:24 + manifest_size])
    if not manifest.IsInitialized() or manifest.block_size != 4096:
        raise ValueError('unsupported manifest or block size')
    report = {'url': args.url, 'zip_size': remote.size, 'etag': remote.etag,
              'schema_commit': SCHEMA_COMMIT, 'schema_sha256': sha(schema),
              'payload_offset': offset, 'payload_metadata_sha256': sha(header),
              'properties_metadata_sha256': sha(header[:24 + manifest_size]),
              'metadata_hash_verified': True, 'whole_zip_hash_verified': False,
              'whole_payload_hash_verified': False, 'vendor_signature_authenticated': False,
              'ota_metadata': metadata, 'partitions': [], 'extracted': []}
    for p in manifest.partitions:
        info = {'name': p.partition_name, 'size': p.new_partition_info.size,
                'sha256': p.new_partition_info.hash.hex(), 'operations': len(p.operations),
                'operation_types': sorted({o.type for o in p.operations}),
                'incremental': p.HasField('old_partition_info')}
        report['partitions'].append(info)
        print(json.dumps(info), flush=True)
    selected = args.partitions.split(',') if args.partitions else []
    missing = set(selected) - {p.partition_name for p in manifest.partitions}
    if missing:
        raise ValueError(f'partitions absent: {sorted(missing)}')
    remote.chunk_size = 4 * 1024 * 1024
    for p in manifest.partitions:
        if p.partition_name in selected:
            print('Extracting ' + p.partition_name, flush=True)
            result = extract_partition(remote, offset + metadata_size, offset + entry.file_size,
                                       p, manifest.block_size, out)
            report['extracted'].append(result)
            print(json.dumps(result), flush=True)
            report['bytes_downloaded_this_run'] = remote.downloaded
            (out / 'extraction.json').write_text(json.dumps(report, indent=2) + '\n')
    report['bytes_downloaded_this_run'] = remote.downloaded
    (out / 'extraction.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Report: ' + str(out / 'extraction.json'), flush=True)


if __name__ == '__main__':
    main()
