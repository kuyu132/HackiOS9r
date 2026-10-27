import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from build_dynamic_root import verified_entry

spec=importlib.util.spec_from_file_location('dynamic_smoke',Path(__file__).with_name('dynamic-smoke.py'))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)

class DynamicRootTests(unittest.TestCase):
    def test_modified_missing_metadata_and_symlink_inputs_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'dyld').write_bytes(b'original')
            entry={'type':'file','sha256':hashlib.sha256(b'original').hexdigest(),'source_uid':0,'source_gid':0}
            manifest={'entries':{'dyld':entry}}
            self.assertEqual(verified_entry(root,manifest,'dyld')[0],root/'dyld')
            del entry['source_uid']
            with self.assertRaisesRegex(ValueError,'ownership'): verified_entry(root,manifest,'dyld')
            entry['source_uid']=0;(root/'dyld').write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError,'mismatch'): verified_entry(root,manifest,'dyld')
            (root/'target').write_bytes(b'original');(root/'dyld').unlink();(root/'dyld').symlink_to('target')
            with self.assertRaisesRegex(ValueError,'mismatch'): verified_entry(root,manifest,'dyld')

    def test_ram_layout_and_existing_file_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'image';output=root/'ram'
            source.write_bytes(b'root bytes');smoke.prepare_ram(source,output)
            self.assertEqual(output.stat().st_size,smoke.RAM_SIZE)
            with output.open('rb') as f:
                f.seek(smoke.ROOT_ADDRESS-smoke.RAM_BASE);self.assertEqual(f.read(10),b'root bytes')
            with self.assertRaises(FileExistsError): smoke.prepare_ram(source,output)
            self.assertEqual(source.read_bytes(),b'root bytes')

    def test_oversized_root_refused_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'image'
            with source.open('wb') as f: f.truncate(smoke.RAM_SIZE)
            with self.assertRaisesRegex(ValueError,'fit'): smoke.prepare_ram(source,root/'ram')
            self.assertFalse((root/'ram').exists())
