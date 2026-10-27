"""Regressions for the native build's explicit, limited capability contract."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import tempfile
import importlib.util

SPEC=importlib.util.spec_from_file_location('native_builder',Path(__file__).with_name('build-native-kernel.py'))
BUILDER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(BUILDER)

ROOT = Path(__file__).resolve().parents[2]


class NativeBuildTests(unittest.TestCase):
    def test_completed_build_reused_without_overwriting_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);kernel=directory/'kernel';kernel.write_bytes(b'kernel')
            record=directory/'build.json';inputs={'source':'pin'}
            record.write_text(json.dumps({'status':'complete','make_exit_code':0,'inputs':inputs,
                'kernel':{'path':str(kernel),'sha256':BUILDER.sha(kernel)}}))
            before=record.read_bytes()
            self.assertTrue(BUILDER.reuse_build(record,inputs));self.assertEqual(record.read_bytes(),before)
            kernel.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'): BUILDER.reuse_build(record,inputs)
            self.assertEqual(record.read_bytes(),before)

    def test_incomplete_or_changed_build_record_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            record=Path(temp)/'build.json';inputs={'source':'pin'}
            self.assertFalse(BUILDER.reuse_build(record,inputs))
            for status in ['building','failed','interrupted']:
                record.write_text(json.dumps({'status':status,'inputs':inputs}));before=record.read_bytes()
                with self.assertRaisesRegex(RuntimeError,'incomplete'): BUILDER.reuse_build(record,inputs)
                self.assertEqual(record.read_bytes(),before)
            record.write_text(json.dumps({'status':'prepared','inputs':inputs}))
            self.assertFalse(BUILDER.reuse_build(record,inputs))
            with self.assertRaisesRegex(RuntimeError,'differs'): BUILDER.reuse_build(record,{'source':'different'})

    def test_persona_functions_match_fixed_upstream(self):
        source=ROOT/'out/lemonades/xnu-persona-policy-src'
        base=subprocess.check_output(['git','-C',str(source),'show',
            'c54f35ca767986246321eb901baf8f5ff7923f6a:bsd/kern/kern_exec.c'],text=True)
        patch=(ROOT/'xnu/redwood.patch').read_text()
        start=patch.index('diff --git a/bsd/kern/kern_exec.c ')
        end=patch.index('\ndiff --git ',start+1)
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'bsd/kern/kern_exec.c';target.parent.mkdir(parents=True);target.write_text(base)
            subprocess.run(['git','apply','--whitespace=nowarn','-'],cwd=temp,input=patch[start:end]+'\n',
                           text=True,capture_output=True,check=True)
            actual=target.read_text()
        def function(text,name):
            start=text.index('\n'+name+'(');end=text.index('\n}\n',start)+3
            return text[start:end]
        for name in ['spawn_validate_persona','spawn_persona_adopt']:
            self.assertEqual(function(actual,name),function(base,name))

    def test_export_patch_only_removes_the_reviewed_inventory(self):
        inventory = json.loads((ROOT / 'tools/lemonades/native-minimal-exports.json').read_text())['exports_removed']
        patch = (ROOT / 'xnu/native-minimal-exports.patch').read_text()
        removed = {}
        current = None
        for line in patch.splitlines():
            if line.startswith('diff --git '):
                current = line.split()[-1].removeprefix('b/config/')
                self.assertIn(current, inventory)
                removed[current] = []
            elif line.startswith('-') and not line.startswith('---'):
                removed[current].append(line[1:].strip())
            elif line.startswith('+') and not line.startswith('+++'):
                self.fail('profile may remove optional exports, not insert replacements or suppress checks')
        self.assertEqual(removed, inventory)
        self.assertEqual(sum(map(len, removed.values())), 131)
        self.assertTrue(all('*' not in s and ':' not in s for rows in removed.values() for s in rows))
        for name in ['IOKit.exports', 'Libkern.exports']:
            self.assertTrue(all('5IORPC' in s for s in removed[name]))

    def test_platform_header_is_exported_and_native_profile_is_separate(self):
        patch = (ROOT / 'xnu/redwood.patch').read_text()
        self.assertIn('+\t\t    hackios_platform.h \\', patch)
        self.assertNotIn('diff --git a/config/Private.exports', patch)
        apply = (ROOT / 'xnu/apply.sh').read_text()
        self.assertNotIn('native-minimal-exports.patch', apply)
        export = (ROOT / 'xnu/export.sh').read_text()
        self.assertIn('native minimal export profile is applied', export)

    def test_type_builtin_switch_is_defined_for_both_compilers(self):
        compilers = [shutil.which('clang'), '/opt/homebrew/opt/llvm/bin/clang']
        program = '''
#ifndef XNU_NO_TYPE_BUILTINS
#error type builtin policy is undefined
#endif
#if __has_builtin(__builtin_xnu_type_signature)
_Static_assert(XNU_NO_TYPE_BUILTINS == 0, "use native builtins");
#else
_Static_assert(XNU_NO_TYPE_BUILTINS == 1, "use compatibility builtins");
#endif
'''
        for compiler in compilers:
            if not compiler or not Path(compiler).is_file():
                continue
            with self.subTest(compiler=compiler):
                subprocess.run([compiler, '-std=c11', '-fsyntax-only', '-x', 'c', '-', '-include',
                    str(ROOT / 'xnu-deps/hostinc/xnu_clang_compat.h')], input=program,
                    text=True, capture_output=True, check=True)

    def test_dependency_pins_and_sdk_metadata_disclosure(self):
        lock = json.loads((ROOT / 'tools/lemonades/native-deps-lock.json').read_text())
        for repo in lock['repositories'].values():
            self.assertRegex(repo['commit'], r'^[0-9a-f]{40}$')
            self.assertTrue(repo['url'].startswith('https://github.com/'))
        self.assertRegex(lock['mac_sdk']['sha256'], r'^[0-9a-f]{64}$')
        self.assertIn('16.4', lock['sdk_note'])


if __name__ == '__main__':
    unittest.main()
