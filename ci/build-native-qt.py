#!/usr/bin/env python3
"""Build native desktop Qt from the same verified sources as Windows depends."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_spec(package):
    text = (ROOT / 'depends/packages' / (package + '.mk')).read_text()
    version = re.search(r'^\$\(package\)_version=(\S+)$', text, re.M).group(1)
    digest = re.search(r'^\$\(package\)_sha256_hash=([0-9a-f]{64})$', text, re.M).group(1)
    module = {'qt': 'qtbase', 'native_qttools': 'qttools', 'qt5compat': 'qt5compat'}[package]
    archive = f'{module}-everywhere-src-{version}.tar.xz'
    url = f'https://download.qt.io/official_releases/qt/{version.rsplit(".", 1)[0]}/{version}/submodules/{archive}'
    return archive, url, digest


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--cmake', required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    sources = ROOT / 'depends/sources'
    work = ROOT / 'qt-native-work'
    sources.mkdir(parents=True, exist_ok=True)
    common = ['-G', 'Unix Makefiles', f'-DCMAKE_INSTALL_PREFIX={prefix}',
              f'-DCMAKE_PREFIX_PATH={prefix}', f'-DCMAKE_INSTALL_RPATH={prefix}/lib',
              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_LIBDIR=lib',
              '-DBUILD_SHARED_LIBS=ON', '-DQT_BUILD_TESTS=OFF', '-DQT_BUILD_EXAMPLES=OFF']
    if sys.platform == 'darwin':
        common += ['-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0', '-DFEATURE_framework=OFF']
    for package in ('qt', 'native_qttools', 'qt5compat'):
        archive, url, digest = source_spec(package)
        cached = sources / archive
        if not cached.exists():
            partial = cached.with_suffix('.partial')
            run('curl', '--fail', '--location', '--retry', '3', '--output', partial, url)
            partial.replace(cached)
        if hashlib.sha256(cached.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Checksum mismatch: {cached}')
        source = work / archive.removesuffix('.tar.xz')
        if source.exists():
            shutil.rmtree(source)
        work.mkdir(exist_ok=True)
        run('tar', '-xf', cached, '-C', work)
        options = list(common)
        if package == 'qt':
            options += [f'-DFEATURE_system_{name}=OFF' for name in
                        ('zlib', 'pcre2', 'doubleconversion', 'libb2', 'freetype', 'harfbuzz', 'png', 'jpeg')]
            options += [f'-DFEATURE_{name}=OFF' for name in
                        ('icu', 'zstd', 'dbus', 'sql', 'opengl', 'printsupport', 'glib')]
            options += ['-DINPUT_opengl=no', '-DFEATURE_gui=ON', '-DFEATURE_widgets=ON',
                        '-DFEATURE_network=ON', '-DFEATURE_testlib=ON']
            if sys.platform.startswith('linux'):
                options += ['-DFEATURE_xcb=ON']
        elif package == 'native_qttools':
            options += [f'-DFEATURE_{name}=OFF' for name in
                        ('assistant', 'designer', 'qdoc', 'clang', 'distancefieldgenerator',
                         'pixeltool', 'qdbus', 'qtdiag', 'qtplugininfo', 'kmap2qmap')]
            options += ['-DFEATURE_linguist=ON']
        run(args.cmake, '-S', source, '-B', source / 'build', *options)
        run(args.cmake, '--build', source / 'build', '--parallel', args.jobs)
        run(args.cmake, '--install', source / 'build')
        shutil.copytree(source / 'LICENSES', prefix / 'share/licenses' / package, dirs_exist_ok=True)
        shutil.rmtree(source)
    (prefix / '.complete').write_text('Qt native desktop build complete\n')


if __name__ == '__main__':
    main()
