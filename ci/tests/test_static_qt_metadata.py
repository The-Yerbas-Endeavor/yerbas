"""Regression coverage for CMake's MinGW response-file flags."""
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
            (target / 'link.txt').write_text('g++ @CMakeFiles/qt_link_probe.dir/objects1.rsp -o qt_link_probe.exe @CMakeFiles/qt_link_probe.dir/linkLibs.rsp')
            with patch.object(BUILD, 'run'):
                BUILD.static_metadata(prefix, 'cmake', 2, 'x86_64-w64-mingw32')
            pc = (prefix / 'lib/pkgconfig/Qt6Core.pc').read_text()
            self.assertNotIn('@CMakeFiles', pc)
            self.assertNotIn('main.cpp.obj', pc)
            self.assertIn(str(target / 'plugin.cpp.obj'), pc)
            self.assertIn('/qt/lib/libQt6Core.a -lkernel32', pc)
            self.assertIn('-I/qt headers/QtCore', pc)
            self.assertIn('-I/qt/QtWidgets', pc)
            self.assertNotIn('-isystem', pc)

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
