"""Exercise packaging behavior without requiring a full Qt build."""
import importlib.util
import os
import sys
from unittest.mock import patch
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('package_native_qt', Path(__file__).parents[1] / 'package-native-qt.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class NativeQtPackagingTests(unittest.TestCase):
    def test_relocated_linux_launcher_preserves_arguments_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / 'qt'
            (prefix / 'lib').mkdir(parents=True)
            (prefix / 'plugins/platforms').mkdir(parents=True)
            (prefix / 'lib/libQt6Core.so.6.12.0').write_text('library fixture')
            (prefix / 'lib/libQt6Core.so.6').symlink_to('libQt6Core.so.6.12.0')
            (prefix / 'plugins/platforms/libqminimal.so').write_text('plugin fixture')
            source = root / 'source'
            source.mkdir()
            (source / '.libs').mkdir()
            (source / 'wallet').write_text('invalid libtool wrapper; must not be packaged')
            (source / '.libs/wallet').write_text('#!/bin/sh\nprintf "%s\\n" "$LD_LIBRARY_PATH" "$QT_PLUGIN_PATH" "$@"\n')
            PACKAGE.linux_bundle(prefix, root / 'package', source / 'wallet', 'yerbas-qt')
            moved = root / 'relocated wallet'
            (root / 'package').rename(moved)
            shutil.rmtree(prefix)
            output = subprocess.check_output([str(moved / 'bin/yerbas-qt'), 'argument with spaces'], text=True).splitlines()
            self.assertEqual(output[0].split(':')[0], str(moved / 'lib'))
            self.assertEqual(output[1], str(moved / 'plugins'))
            self.assertEqual(output[2], 'argument with spaces')
            self.assertEqual((moved / 'lib/libQt6Core.so.6').read_text(), 'library fixture')
            self.assertTrue((moved / 'plugins/platforms/libqminimal.so').is_file())

    def test_mac_dylib_paths_are_relocatable_and_missing_libraries_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Test.app'
            binary = app / 'Contents/MacOS/test'
            library = app / 'Contents/Frameworks/libQt6Test.6.dylib'
            plugin = app / 'Contents/PlugIns/platforms/libqminimal.dylib'
            for file in (binary, library, plugin):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('Mach-O fixture')
            def otool(command, **kwargs):
                if command[1] == '-L':
                    return 'Mach-O:\n\t/build/qt/lib/libQt6Test.6.dylib (compatibility version 6.0.0)\n'
                return 'Load command 1\n cmd LC_RPATH\n cmdsize 48\n path /build/qt/lib (offset 12)\n'
            with patch.object(PACKAGE.subprocess, 'check_output', side_effect=otool), patch.object(PACKAGE.subprocess, 'run') as run:
                PACKAGE.mac_runtime_paths(app, 'test')
                calls = [c.args[0] for c in run.call_args_list]
                self.assertIn(['install_name_tool', '-add_rpath', '@loader_path/../Frameworks', str(binary)], calls)
                self.assertIn(['install_name_tool', '-add_rpath', '@loader_path', str(library)], calls)
                self.assertIn(['install_name_tool', '-add_rpath', '@loader_path/../../Frameworks', str(plugin)], calls)
                self.assertIn(['install_name_tool', '-change', '/build/qt/lib/libQt6Test.6.dylib', '@rpath/libQt6Test.6.dylib', str(binary)], calls)
                library.unlink()
                with self.assertRaisesRegex(RuntimeError, 'Missing bundled Qt dependency'):
                    PACKAGE.mac_runtime_paths(app, 'test')

    def test_mac_existing_bundle_rpath_is_not_added_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Test.app'
            binary = app / 'Contents/MacOS/test'
            binary.parent.mkdir(parents=True)
            binary.write_text('Mach-O fixture')
            def otool(command, **kwargs):
                if command[1] == '-L':
                    return 'Mach-O:\n'
                return 'Load command 1\n cmd LC_RPATH\n cmdsize 48\n path @loader_path/../Frameworks (offset 12)\n'
            with patch.object(PACKAGE.subprocess, 'check_output', side_effect=otool), patch.object(PACKAGE.subprocess, 'run') as run:
                PACKAGE.mac_runtime_paths(app, 'test')
                run.assert_not_called()

    def test_mac_test_plugin_and_paths_are_fixed_before_signing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / 'qt'
            plugin = prefix / 'plugins/platforms/libqminimal.dylib'
            plugin.parent.mkdir(parents=True)
            plugin.write_text('minimal plugin')
            source = root / 'test'
            source.write_text('executable')
            events = []
            def paths(app, name):
                self.assertEqual((app / 'Contents/PlugIns/platforms/libqminimal.dylib').read_text(), 'minimal plugin')
                events.append('paths')
            with patch.object(PACKAGE, 'mac_runtime_paths', side_effect=paths), patch.object(PACKAGE.subprocess, 'run', side_effect=lambda command, **kwargs: events.append(command[0])):
                PACKAGE.mac_bundle(prefix, root / 'out', source, 'test', '1.0', test_runtime=True)
            self.assertEqual(events, [str(prefix / 'bin/macdeployqt'), 'paths', 'codesign', 'codesign'])

    @unittest.skipUnless(sys.platform == 'darwin', 'requires the macOS loader and toolchain')
    def test_real_mac_dylib_loads_after_bundle_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'build'
            original.mkdir()
            (original / 'library.c').write_text('int answer(void) { return 42; }')
            (original / 'main.c').write_text('int answer(void); int main(void) { return answer() != 42; }')
            dylib = original / 'libQt6Test.6.dylib'
            subprocess.run(['clang', '-dynamiclib', str(original / 'library.c'), '-Wl,-install_name,@rpath/libQt6Test.6.dylib', '-o', str(dylib)], check=True)
            app = root / 'Test.app'
            binary = app / 'Contents/MacOS/test'
            binary.parent.mkdir(parents=True)
            subprocess.run(['clang', str(original / 'main.c'), str(dylib), '-o', str(binary)], check=True)
            libraries = app / 'Contents/Frameworks'
            libraries.mkdir()
            shutil.copy2(dylib, libraries / dylib.name)
            env = {k: v for k, v in os.environ.items() if not k.startswith('DYLD_')}
            self.assertNotEqual(subprocess.run([str(binary)], env=env, capture_output=True).returncode, 0)
            PACKAGE.mac_runtime_paths(app, 'test')
            for file in (libraries / dylib.name, binary):
                subprocess.run(['codesign', '--force', '--sign', '-', str(file)], check=True)
            moved = root / 'relocated test.app'
            app.rename(moved)
            shutil.rmtree(original)
            subprocess.run([str(moved / 'Contents/MacOS/test')], env=env, check=True)

    def test_missing_binary_fails_instead_of_shipping_partial_wallet(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                PACKAGE.executable(Path(tmp) / 'missing', Path(tmp) / 'package/wallet')


if __name__ == '__main__':
    unittest.main()
