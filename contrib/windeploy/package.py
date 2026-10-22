#!/usr/bin/env python3
"""Package a Linux-cross-compiled Windows wallet and its PE DLL dependencies."""
import argparse
import re
import shutil
import subprocess
from pathlib import Path

# Windows supplies these libraries. Unknown imports must resolve from the SDK or
# compiler; silently omitting one would produce a ZIP that cannot start.
SYSTEM_DLLS = set('''advapi32 authz avrt bcrypt bcryptprimitives cfgmgr32 comctl32
comdlg32 crypt32 cryptbase cryptnet cryptsp d2d1 d3d9 d3d11 d3d12 dbghelp dnsapi
 dwmapi dwrite dxgi dxguid gdi32 glu32 imm32 iphlpapi kernel32 mpr mscms msimg32 msvcrt
 ncrypt netapi32 ntdll ole32 oleacc oleaut32 opengl32 powrprof propsys psapi rasapi32
 rpcrt4 runtimeobject secur32 setupapi shell32 shcore shlwapi sspicli ucrtbase
 user32 userenv usp10 uxtheme version windowscodecs winhttp wininet winmm
 winspool wintrust ws2_32 wtsapi32 wldap32 normaliz'''.split())


def imports(binary, objdump):
    result = subprocess.run([objdump, '-p', str(binary)], check=True,
                            capture_output=True, text=True)
    return re.findall(r'DLL Name:\s*(\S+)', result.stdout)


def is_system(name):
    name = name.lower()
    return name.startswith(('api-ms-win-', 'ext-ms-win-')) or name.removesuffix('.dll') in SYSTEM_DLLS


def copy_runtime(prefix, destination, compiler, objdump):
    available = {p.name.lower(): p for p in (prefix / 'bin').glob('*.dll')}
    pending = list(destination.rglob('*.exe')) + list(destination.rglob('*.dll'))
    checked = set()
    unresolved = set()
    copied = {p.name.lower(): p for p in destination.glob('*.dll')}
    while pending:
        binary = pending.pop()
        if binary in checked:
            continue
        checked.add(binary)
        for name in imports(binary, objdump):
            if is_system(name):
                continue
            target = copied.get(name.lower(), destination / name)
            if target.exists():
                pending.append(target)
                continue
            source = available.get(name.lower())
            if source is None:
                result = subprocess.run([compiler, '-print-file-name=' + name],
                                        check=True, capture_output=True, text=True)
                candidate = Path(result.stdout.strip())
                if candidate.is_absolute() and candidate.is_file():
                    source = candidate
            if source is None:
                unresolved.add(f'Unresolved DLL {name}, required by {binary.name}')
                continue
            target = destination / source.name
            shutil.copy2(source, target)
            copied[name.lower()] = target
            pending.append(target)

    if unresolved:
        raise RuntimeError('\n'.join(sorted(unresolved)))


def built_executable(path):
    """Prefer the real PE executable over libtool's build-tree launcher."""
    real = path.parent / '.libs' / path.name
    return real if real.is_file() else path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--depends', required=True, type=Path)
    parser.add_argument('--build', default=Path('.'), type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tests-output', required=True, type=Path)
    parser.add_argument('--host', default='x86_64-w64-mingw32')
    args = parser.parse_args()
    prefix, build = args.depends.resolve(), args.build.resolve()
    output, tests = args.output.resolve(), args.tests_output.resolve()
    for dest in (output, tests):
        if dest.exists() and any(dest.iterdir()):
            parser.error(f'Output directory must be empty: {dest}')
    bin_dir = output / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    for binary in ('yerbasd.exe', 'yerbas-cli.exe', 'qt/yerbas-qt.exe'):
        shutil.copy2(built_executable(build / 'src' / binary), bin_dir / Path(binary).name)
    for group in ('platforms', 'imageformats', 'tls', 'styles'):
        plugins = prefix / 'plugins' / group
        if plugins.exists():
            for dll in plugins.glob('*.dll'):
                dest = bin_dir / 'plugins' / group
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dll, dest / dll.name)
    for required in ('platforms/qwindows.dll', 'platforms/qminimal.dll',
                     'tls/qschannelbackend.dll', 'imageformats/qjpeg.dll',
                     'imageformats/qgif.dll'):
        if not (bin_dir / 'plugins' / required).is_file():
            raise RuntimeError(f'Missing required Qt plugin: {required}')
    (bin_dir / 'qt.conf').write_text('[Paths]\nPrefix=.\nPlugins=plugins\n', encoding='utf-8')
    copy_runtime(prefix, bin_dir, args.host + '-g++', args.host + '-objdump')
    shutil.copytree(bin_dir, tests, dirs_exist_ok=True)
    for binary in ('test/test_yerbas.exe', 'qt/test/test_yerbas-qt.exe'):
        shutil.copy2(built_executable(build / 'src' / binary), tests / Path(binary).name)
    copy_runtime(prefix, tests, args.host + '-g++', args.host + '-objdump')
    shutil.copytree(prefix / 'share/licenses', output / 'licenses')
    notices = output / 'licenses/toolchain'
    notices.mkdir(parents=True)
    packages = ('gcc-mingw-w64-x86-64-posix-runtime',
                'g++-mingw-w64-x86-64-posix', 'mingw-w64-common',
                'mingw-w64-x86-64-dev')
    versions = subprocess.check_output(
        ['dpkg-query', '-W', '-f=${Package} ${Version}\\n', *packages], text=True)
    (notices / 'packages.txt').write_text(versions, encoding='utf-8')
    for package in packages:
        shutil.copy2(Path('/usr/share/doc') / package / 'copyright', notices / (package + '.copyright'))
    repo = Path(__file__).resolve().parents[2]
    shutil.copy2(repo / 'COPYING', output / 'COPYING')
    shutil.copy2(repo / 'doc/windows-runtime-notices.md', output / 'RUNTIME-NOTICES.md')
    print(f'Windows wallet package: {output}')
    print(f'Windows runtime and test executables: {tests}')


if __name__ == '__main__':
    main()
