#!/usr/bin/env python3
"""Package native Qt wallets and GUI tests; Windows uses contrib/windeploy."""
import argparse
import os
import re
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def executable(source, destination):
    source = Path(source)
    real = source.parent / '.libs' / source.name
    if real.exists():
        source = real
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)


def linux_bundle(prefix, target, source, name):
    target = Path(target)
    executable(source, target / 'libexec' / name)
    libraries = target / 'lib'
    libraries.mkdir(exist_ok=True)
    for item in (prefix / 'lib').glob('*.so*'):
        shutil.copy2(item, libraries / item.name, follow_symlinks=False)
    shutil.copytree(prefix / 'plugins', target / 'plugins', dirs_exist_ok=True, symlinks=True)
    (target / 'bin').mkdir(exist_ok=True)
    launcher = target / 'bin' / name
    launcher.write_text('#!/bin/sh\nset -eu\n'
                        'root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
                        'export LD_LIBRARY_PATH="$root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                        'export QT_PLUGIN_PATH="$root/plugins"\n'
                        f'exec "$root/libexec/{name}" "$@"\n')
    launcher.chmod(0o755)


def mac_runtime_paths(app, name):
    """Resolve Qt from the bundle, including non-framework Qt dylib builds."""
    contents = app / 'Contents'
    frameworks = contents / 'Frameworks'
    binary = contents / 'MacOS' / name
    for item in [binary, *frameworks.rglob('*.dylib'), *(contents / 'PlugIns').rglob('*.dylib')]:
        if item.is_symlink():
            continue
        dependencies = subprocess.check_output(['otool', '-L', str(item)], text=True)
        for line in dependencies.splitlines()[1:]:
            dependency = line.strip().split(' (', 1)[0]
            library = Path(dependency).name
            if library.startswith('libQt6') and library.endswith('.dylib'):
                if not (frameworks / library).is_file():
                    raise RuntimeError(f'Missing bundled Qt dependency: {library} ({item})')
                bundled = '@rpath/' + library
                if dependency != bundled:
                    subprocess.run(['install_name_tool', '-change', dependency, bundled, str(item)], check=True)
        relative = os.path.relpath(frameworks, item.parent)
        rpath = '@loader_path' if relative == '.' else '@loader_path/' + relative
        commands = subprocess.check_output(['otool', '-l', str(item)], text=True)
        existing = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset \d+\)', commands)
        if rpath not in existing:
            subprocess.run(['install_name_tool', '-add_rpath', rpath, str(item)], check=True)


def mac_bundle(prefix, target, source, name, version, *, test_runtime=False):
    app = Path(target) / (name + '.app')
    contents = app / 'Contents'
    executable(source, contents / 'MacOS' / name)
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleExecutable': name, 'CFBundleName': name,
                       'CFBundleIdentifier': 'org.yerbas.' + name,
                       'CFBundlePackageType': 'APPL', 'CFBundleVersion': version,
                       'CFBundleShortVersionString': version,
                       'LSMinimumSystemVersion': '15.0',
                       'NSHighResolutionCapable': True}, stream)
    subprocess.run([str(prefix / 'bin/macdeployqt'), str(app), '-verbose=2'], check=True)
    if test_runtime:
        # test_main explicitly selects minimal; macdeployqt deploys cocoa only.
        plugins = contents / 'PlugIns/platforms'
        plugins.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prefix / 'plugins/platforms/libqminimal.dylib', plugins / 'libqminimal.dylib')
    mac_runtime_paths(app, name)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('package'))
    parser.add_argument('--tests-output', type=Path, default=Path('test-binaries'))
    args = parser.parse_args()
    version = dict(line.split('=', 1) for line in Path('build.properties').read_text().splitlines())['release-version']
    for target in (args.output, args.tests_output):
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(args.prefix / 'share/licenses', target / 'share/licenses/qt', dirs_exist_ok=True)
    if sys.platform == 'darwin':
        mac_bundle(args.prefix, args.output, 'src/qt/yerbas-qt', 'Yerbas-Qt', version)
        mac_bundle(args.prefix, args.tests_output, 'src/qt/test/test_yerbas-qt', 'test_yerbas-qt', version, test_runtime=True)
        (args.output / 'README-Qt.txt').write_text(
            'Yerbas-Qt.app includes Qt. Built for macOS 15 Intel.\n'
            'This CI build is ad-hoc signed, not Developer ID signed or notarized.\n')
    else:
        linux_bundle(args.prefix, args.output, 'src/qt/yerbas-qt', 'yerbas-qt')
        linux_bundle(args.prefix, args.tests_output, 'src/qt/test/test_yerbas-qt', 'test_yerbas-qt')
        (args.output / 'README-Qt.txt').write_text(
            'Run bin/yerbas-qt; keep the entire extracted directory together.\n'
            'Qt libraries and plugins are included. Use the Ubuntu version/architecture in the archive name.\n'
            'Desktop runtime: sudo apt-get install libfontconfig1 libxkbcommon-x11-0 libxcb-cursor0 '
            'libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0\n')


if __name__ == '__main__':
    main()
