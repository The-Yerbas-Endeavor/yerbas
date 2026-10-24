"""Exercise packaging behavior without requiring a full Qt build."""
import importlib.util
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

    def test_missing_binary_fails_instead_of_shipping_partial_wallet(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                PACKAGE.executable(Path(tmp) / 'missing', Path(tmp) / 'package/wallet')


if __name__ == '__main__':
    unittest.main()
