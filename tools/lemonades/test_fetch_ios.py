import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from fetch_ios import LOCK, ROOT, download, validate_manifest, validate_member

class IosImportTests(unittest.TestCase):
    def manifest(self):
        return (ROOT/'out/lemonades/ios165-source/BuildManifest.plist').read_bytes()

    def test_observed_manifest_matches_lock(self):
        self.assertEqual(validate_manifest(self.manifest())['DeviceClass'],'d22ap')

    def test_manifest_hash_and_identity_rejected(self):
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            validate_manifest(self.manifest()+b'\0')
        lock=copy.deepcopy(LOCK);lock['device_class']='lemonades'
        with self.assertRaisesRegex(ValueError,'identity'):
            validate_manifest(self.manifest(),lock)
        lock=copy.deepcopy(LOCK);lock['components']['rootfs']['name']='different.dmg'
        with self.assertRaisesRegex(ValueError,'component path'):
            validate_manifest(self.manifest(),lock)

    def fixture(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as z:
            z.writestr('fixture.dmg',b'bounded image content')
        buffer.seek(0)
        archive=zipfile.ZipFile(buffer)
        info=archive.getinfo('fixture.dmg')
        component={'name':info.filename,'size':info.file_size,'compressed_size':info.compress_size,'crc32':hex(info.CRC)}
        return buffer,archive,component

    def test_download_reuse_and_changed_local_file_rejected(self):
        _,archive,component=self.fixture()
        with archive, tempfile.TemporaryDirectory() as temp:
            output=Path(temp)
            first=download(archive,component,output)
            self.assertTrue(first['zip_crc_verified'])
            self.assertFalse(first['apple_image_signature_verified'])
            self.assertEqual(first,download(archive,component,output))
            (output/component['name']).write_bytes(b'not the image')
            with self.assertRaisesRegex(ValueError,'verification'):
                download(archive,component,output)

    def test_invalid_zip_metadata_rejected(self):
        _,archive,component=self.fixture()
        with archive:
            info=archive.getinfo(component['name'])
            for key,value in [('size',0),('compressed_size',0),('crc32','0x0'),('name','../fixture.dmg')]:
                changed={**component,key:value}
                with self.assertRaises(ValueError): validate_member(info,changed)

    def test_corrupt_stream_never_publishes_image(self):
        buffer,archive,component=self.fixture()
        archive.close()
        raw=bytearray(buffer.getvalue());raw[30+len(component['name'])]^=0xff
        with zipfile.ZipFile(io.BytesIO(raw)) as corrupted, tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(zipfile.BadZipFile): download(corrupted,component,Path(temp))
            self.assertEqual(list(Path(temp).iterdir()),[])

if __name__=='__main__': unittest.main()
