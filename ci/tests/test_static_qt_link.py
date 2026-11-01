"""Validate the CMake-to-Autotools static link boundary."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('static_qt_link', Path(__file__).parents[1] / 'static-qt-link.py')
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


class StaticQtLinkTests(unittest.TestCase):
    def test_linux_keeps_plugin_initializers_and_library_order(self):
        root = Path('/build')
        command = ('/usr/bin/c++ -O3 CMakeFiles/wallet.dir/probe.cpp.o '
                   'CMakeFiles/qxcb_init.dir/import.cpp.o -o wallet '
                   '/qt/plugins/platforms/libqxcb.a /qt/lib/libQt6Gui.a -lX11')
        self.assertEqual(link.link_flags(command, root),
                         '-O3 /build/CMakeFiles/qxcb_init.dir/import.cpp.o '
                         '/qt/plugins/platforms/libqxcb.a /qt/lib/libQt6Gui.a -lX11')

    def test_windows_response_files_keep_runtime_and_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'objects.rsp').write_text('CMakeFiles/wallet.dir/probe.cpp.obj plugins/init.obj')
            (root / 'libs.rsp').write_text('/qt/lib/libQt6Widgets.a -luser32 -lwinpthread')
            flags = link.link_flags('g++ -static @objects.rsp -o wallet.exe '
                                    '-Wl,--out-implib,libwallet.dll.a @libs.rsp', root)
            self.assertEqual(flags, f'-static {root}/plugins/init.obj '
                             '/qt/lib/libQt6Widgets.a -luser32 -lwinpthread')

    def test_paths_with_spaces_fail_instead_of_silently_mislinking(self):
        with self.assertRaises(ValueError):
            link.link_flags('c++ "plugin directory/import.o" -o wallet', Path('/build'))

    def test_symlinked_build_directory_resolves_plugin_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = root / 'actual'
            actual.mkdir()
            alias = root / 'alias'
            alias.symlink_to(actual, target_is_directory=True)
            flags = link.link_flags('c++ plugins/init.obj -o wallet', alias)
            self.assertEqual(flags, str(actual / 'plugins/init.obj'))


if __name__ == '__main__':
    unittest.main()
