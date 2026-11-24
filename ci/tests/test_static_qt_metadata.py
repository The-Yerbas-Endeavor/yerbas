"""Regression coverage for exporting CMake static Qt linker flags."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('build_native_qt', Path(__file__).parents[1] / 'build-native-qt.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class StaticMetadataTests(unittest.TestCase):
    def test_windows_response_files_export_headers_plugins_and_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            build = prefix / 'static-link/build'
            target = build / 'CMakeFiles/qt_link_probe.dir'
            target.mkdir(parents=True)
            (prefix / 'lib').mkdir()
            (target / 'includes_CXX.rsp').write_text('-isystem "/qt headers/QtCore" -I/qt/QtWidgets')
            (target / 'objects1.rsp').write_text('CMakeFiles/qt_link_probe.dir/main.cpp.obj CMakeFiles/qt_link_probe.dir/plugin.cpp.obj')
            (target / 'linkLibs.rsp').write_text('/qt/lib/libQt6Core.a -lkernel32')
            (target / 'flags.make').write_text('CXX_DEFINES = -DQT_STATIC\nCXX_INCLUDES = @CMakeFiles/qt_link_probe.dir/includes_CXX.rsp\n')
            (target / 'link.txt').write_text(
                'cmake -E rm -f CMakeFiles/qt_link_probe.dir/objects.a\n'
                'ar qc CMakeFiles/qt_link_probe.dir/objects.a @CMakeFiles/qt_link_probe.dir/objects1.rsp\n'
                'g++ -Wl,--whole-archive CMakeFiles/qt_link_probe.dir/objects.a '
                '-Wl,--no-whole-archive -o qt_link_probe.exe '
                '@CMakeFiles/qt_link_probe.dir/linkLibs.rsp\n')
            with patch.object(BUILD, 'run'):
                BUILD.static_metadata(prefix, 'cmake', 2, 'x86_64-w64-mingw32')
            pc = (prefix / 'lib/pkgconfig/Qt6Core.pc').read_text()
            self.assertNotIn('@CMakeFiles', pc)
            self.assertNotIn('main.cpp.obj', pc)
            self.assertNotIn('objects.a', pc)
            self.assertNotIn(' -f ', pc)
            self.assertNotIn('cmake -E', pc)
            self.assertIn(str(target / 'plugin.cpp.obj'), pc)
            self.assertIn('/qt/lib/libQt6Core.a -lkernel32', pc)
            self.assertIn('-I/qt headers/QtCore', pc)
            self.assertIn('-I/qt/QtWidgets', pc)
            self.assertNotIn('-isystem', pc)

    def test_depends_metadata_copies_plugins_and_relocates_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / 'depends'
            staging = root / 'stage'
            probe = root / 'probe'
            target = probe / 'build/CMakeFiles/qt_link_probe.dir'
            target.mkdir(parents=True)
            (target / 'plugin.cpp.o').write_bytes(b'plugin object')
            (target / 'flags.make').write_text(
                f'CXX_DEFINES = -DQT_STATIC\nCXX_INCLUDES = -isystem {prefix}/include/QtCore\n')
            (target / 'link.txt').write_text(
                'c++ CMakeFiles/qt_link_probe.dir/main.cpp.o '
                'CMakeFiles/qt_link_probe.dir/plugin.cpp.o -o qt_link_probe '
                f'{staging}/lib/libQt6Core5Compat.a {prefix}/lib/libQt6Core.a -lxcb\n')
            with (patch.object(BUILD, 'run'),
                  patch.object(BUILD, 'linux_static_desktop_link', side_effect=lambda link, *_: link),
                  patch.object(BUILD, 'check_linux_elf')):
                BUILD.static_metadata(prefix, 'cmake', 2, staging_prefix=staging, probe_dir=probe)
            pc = (staging / 'lib/pkgconfig/Qt6Core.pc').read_text()
            self.assertNotIn(str(root), pc)
            self.assertIn('prefix=${pcfiledir}/../..', pc)
            self.assertIn('${prefix}/include/QtCore', pc)
            self.assertIn('${prefix}/lib/libQt6Core5Compat.a', pc)
            self.assertIn('${prefix}/lib/libQt6Core.a', pc)
            self.assertIn('-lxcb', pc)
            self.assertIn('${prefix}/lib/yerbas-qt/2-plugin.cpp.o', pc)
            self.assertEqual((staging / 'lib/yerbas-qt/2-plugin.cpp.o').read_bytes(),
                             b'plugin object')

    def test_windows_staging_exports_relocatable_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / 'depends'
            staging = root / 'stage'
            probe = root / 'probe'
            target = probe / 'build/CMakeFiles/qt_link_probe.dir'
            target.mkdir(parents=True)
            (target / 'plugin.cpp.obj').write_bytes(b'Windows plugin object')
            (target / 'flags.make').write_text(
                f'CXX_DEFINES = -DQT_STATIC\nCXX_INCLUDES = -I{prefix}/include/QtCore\n')
            (target / 'link.txt').write_text(
                'x86_64-w64-mingw32-g++ CMakeFiles/qt_link_probe.dir/main.cpp.obj '
                'CMakeFiles/qt_link_probe.dir/plugin.cpp.obj -o qt_link_probe.exe '
                f'{staging}/lib/libQt6Core5Compat.a {prefix}/lib/libQt6Core.a -lkernel32\n')
            with (patch.object(BUILD, 'run') as cmake,
                  patch.object(BUILD, 'linux_static_desktop_link') as linux_link):
                BUILD.static_metadata(prefix, 'cmake', 2, 'x86_64-w64-mingw32', staging, probe)
            linux_link.assert_not_called()
            self.assertIn(f'-DQt6Core5Compat_DIR={staging}/lib/cmake/Qt6Core5Compat',
                          cmake.call_args_list[0].args)
            pc = (staging / 'lib/pkgconfig/Qt6Core.pc').read_text()
            self.assertNotIn(str(root), pc)
            self.assertIn('libexecdir=${prefix}/native/libexec', pc)
            self.assertIn('${prefix}/lib/libQt6Core5Compat.a', pc)
            self.assertIn('${prefix}/lib/yerbas-qt/2-plugin.cpp.obj', pc)
            self.assertTrue((staging / 'lib/yerbas-qt/2-plugin.cpp.obj').is_file())

    def test_missing_response_file_fails_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                BUILD.expand_response_files(['@missing.rsp'], Path(tmp))

    def test_recursive_response_file_fails_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'loop.rsp').write_text('@loop.rsp')
            with self.assertRaisesRegex(ValueError, 'Recursive response file'):
                BUILD.expand_response_files(['@loop.rsp'], root)
