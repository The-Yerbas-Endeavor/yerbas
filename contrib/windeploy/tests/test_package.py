import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('windeploy', Path(__file__).parents[1] / 'package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class RuntimePackagingTests(unittest.TestCase):
    def test_recursive_imports_plugins_and_compiler_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, dest = root / 'sdk', root / 'out'
            (sdk / 'bin').mkdir(parents=True)
            (dest / 'plugins/platforms').mkdir(parents=True)
            for name in ('Qt6Core.dll', 'Qt6Gui.dll'):
                (sdk / 'bin' / name).write_bytes(b'qt')
            runtime = root / 'libstdc++-6.dll'
            runtime.write_bytes(b'compiler runtime')
            (dest / 'wallet.exe').touch()
            (dest / 'plugins/platforms/qwindows.dll').touch()
            graph = {'wallet.exe': ['Qt6Core.dll', 'KERNEL32.dll'],
                     'qwindows.dll': ['Qt6Gui.dll'],
                     'Qt6Gui.dll': ['qt6core.dll'],
                     'Qt6Core.dll': ['libstdc++-6.dll'],
                     'libstdc++-6.dll': ['api-ms-win-crt-runtime-l1-1-0.dll']}
            with patch.object(package, 'imports', side_effect=lambda p, _: graph[p.name]), \
                 patch.object(package.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, str(runtime))):
                package.copy_runtime(sdk, dest, 'compiler', 'objdump')
            self.assertEqual(sorted(p.name for p in dest.glob('*.dll')),
                             ['Qt6Core.dll', 'Qt6Gui.dll', 'libstdc++-6.dll'])

    def test_schannel_uses_windows_ncrypt_without_bundling_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / 'plugins/tls/qschannelbackend.dll'
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            with patch.object(package, 'imports', return_value=['ncrypt.dll', 'NCRYPT.DLL']), \
                 patch.object(package.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ncrypt.dll')) as compiler:
                package.copy_runtime(root / 'sdk', root, 'compiler', 'objdump')
            compiler.assert_not_called()
            self.assertEqual(list(root.glob('*.dll')), [])

    def test_windows_platform_color_management_is_system_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / 'plugins/platforms/qwindows.dll'
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            # System imports declared by Qt 6.12's Windows platform plugin.
            system_imports = [name + '.dll' for name in (
                'advapi32 comdlg32 d3d9 dwmapi gdi32 imm32 mscms ole32 '
                'oleaut32 runtimeobject setupapi shcore shell32 shlwapi '
                'user32 uxtheme winmm winspool wtsapi32').split()]
            system_imports.append('MSCMS.DLL')
            with patch.object(package, 'imports', return_value=system_imports), \
                 patch.object(package.subprocess, 'run') as compiler:
                package.copy_runtime(root / 'sdk', root, 'compiler', 'objdump')
            compiler.assert_not_called()
            self.assertEqual(list(root.glob('*.dll')), [])

    def test_reports_all_unresolved_imports_across_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'wallet.exe').touch()
            (root / 'plugin.dll').touch()
            graph = {'wallet.exe': ['first.dll', 'second.dll'],
                     'plugin.dll': ['third.dll']}
            with patch.object(package, 'imports', side_effect=lambda p, _: graph[p.name]), \
                 patch.object(package.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'missing.dll')):
                with self.assertRaises(RuntimeError) as error:
                    package.copy_runtime(root / 'sdk', root, 'compiler', 'objdump')
            for name in ('first.dll', 'second.dll', 'third.dll'):
                self.assertIn('Unresolved DLL ' + name, str(error.exception))

    def test_missing_dependency_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'wallet.exe').touch()
            with patch.object(package, 'imports', return_value=['missing.dll']), \
                 patch.object(package.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'missing.dll')):
                with self.assertRaisesRegex(RuntimeError, 'Unresolved DLL missing.dll'):
                    package.copy_runtime(root, root, 'compiler', 'objdump')

    def test_system_dlls_are_not_guessed_for_unknown_libraries(self):
        self.assertTrue(package.is_system('KERNEL32.dll'))
        self.assertTrue(package.is_system('api-ms-win-crt-heap-l1-1-0.dll'))
        self.assertFalse(package.is_system('Qt6Core.dll'))
        self.assertFalse(package.is_system('libwinpthread-1.dll'))


if __name__ == '__main__':
    unittest.main()
