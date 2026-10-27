from pathlib import Path
import plistlib
import unittest
import tempfile
from extract_ios import attached_device, validate_mount, copy_selection, selection_path, selected_metadata

class IosSelectionTests(unittest.TestCase):
    def test_owner_readable_preserves_source_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'etc').mkdir();file=root/'etc/users'
            file.write_bytes(b'fixture');file.chmod(0o600);original=file.stat()
            result=selected_metadata(root,['etc/users'])
            self.assertEqual(set(result),{'etc','etc/users'})
            self.assertEqual(result['etc/users']['mode'],0o600)
            self.assertEqual(result['etc/users']['source_uid'],original.st_uid)
            self.assertEqual(result['etc/users']['source_gid'],original.st_gid)
            self.assertEqual(result['etc/users']['source_size'],7)

    def test_owner_readable_rejects_unbounded_directory_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'etc').mkdir();(root/'link').symlink_to('etc')
            for names in [None,[],['etc'],['link']]:
                with self.subTest(names=names),self.assertRaises(ValueError): selected_metadata(root,names)

    def test_owner_readable_refuses_parent_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mount=root/'mount';mount.mkdir();(root/'file').write_text('outside')
            (mount/'outside').symlink_to(root)
            with self.assertRaisesRegex(ValueError,'source symlink'): selected_metadata(mount,['outside/file'])

    def test_absolute_empty_and_traversal_rejected(self):
        for name in ['', '.', '/usr/lib/dyld', '../dyld', 'usr/../dyld', 'usr\\dyld']:
            with self.subTest(name=name), self.assertRaises(ValueError): selection_path(name)

    def test_leaf_symlink_preserved_without_copying_target(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);mount=base/'mount';mount.mkdir()
            (mount/'link').symlink_to('/not/in/image')
            copy_selection(mount,base/'out',['link'])
            self.assertEqual((base/'out/link').readlink(),Path('/not/in/image'))

    def test_parent_symlink_escape_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);mount=base/'mount';mount.mkdir()
            (base/'secret').write_text('outside');(mount/'escape').symlink_to(base)
            with self.assertRaisesRegex(ValueError,'source symlink'):
                copy_selection(mount,base/'out',['escape/secret'])
            self.assertFalse((base/'out/escape/secret').exists())

class IosMountIdentityTests(unittest.TestCase):
    def data(self,device='/dev/disk73',mount='/owned/mount'):
        return plistlib.dumps({'system-entities':[{'dev-entry':device},
            {'dev-entry':'/dev/disk74s1','mount-point':mount},{'dev-entry':'/dev/disk74'}]})

    def test_disk_from_this_attach_and_exact_mount(self):
        self.assertEqual(attached_device(self.data()),'/dev/disk73')
        validate_mount(self.data(),Path('/owned/mount'))

    def test_no_guessed_disk_when_no_whole_disk(self):
        raw=plistlib.dumps({'system-entities':[{'dev-entry':'/dev/disk73s1','mount-point':'/owned/mount'}]})
        with self.assertRaisesRegex(ValueError,'virtual disk'): attached_device(raw)

    def test_mismatched_mount_rejected_with_device_still_available_for_detach(self):
        raw=self.data(mount='/different')
        self.assertEqual(attached_device(raw),'/dev/disk73')
        with self.assertRaisesRegex(ValueError,'requested path'): validate_mount(raw,Path('/owned/mount'))

if __name__=='__main__': unittest.main()
