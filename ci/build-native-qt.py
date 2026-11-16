#!/usr/bin/env python3
"""Build native desktop Qt from the same verified sources as Windows depends."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import shlex
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


def expand_response_files(tokens, build, active=()):
    """Resolve CMake response files before exporting flags to another build."""
    result = []
    for token in tokens:
        if not token.startswith('@'):
            result.append(token)
            continue
        path = (build / token[1:]).resolve()
        if path in active:
            raise ValueError(f'Recursive response file: {path}')
        result.extend(expand_response_files(shlex.split(path.read_text()), build, (*active, path)))
    return result


def static_metadata(prefix, cmake, jobs, host=None):
    """Resolve static plugins with Qt's CMake targets for our Autotools build."""
    probe = prefix / 'static-link'
    probe.mkdir(exist_ok=True)
    (probe / 'main.cpp').write_text('#include <QApplication>\nint main(int argc, char **argv) { QApplication app(argc, argv); return 0; }\n')
    platform_plugin = 'QWindowsIntegrationPlugin' if host else 'QXcbIntegrationPlugin'
    (probe / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.22)
project(YerbasStaticQt LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network Core5Compat Test)
qt_add_executable(qt_link_probe main.cpp)
target_link_libraries(qt_link_probe PRIVATE Qt6::Widgets Qt6::Network Qt6::Core5Compat Qt6::Test)
qt_import_plugins(qt_link_probe INCLUDE Qt6::PLATFORM_PLUGIN Qt6::QMinimalIntegrationPlugin)
'''.replace('PLATFORM_PLUGIN', platform_plugin))
    build = probe / 'build'
    cross_args = []
    if host:
        cross_args = ['-DCMAKE_SYSTEM_NAME=Windows', f'-DCMAKE_CXX_COMPILER={host}-g++',
                      f'-DCMAKE_C_COMPILER={host}-gcc', f'-DQT_HOST_PATH={prefix}/native']
    run(cmake, '-S', probe, '-B', build, '-G', 'Unix Makefiles',
        f'-DCMAKE_PREFIX_PATH={prefix}', '-DCMAKE_BUILD_TYPE=Release', *cross_args)
    run(cmake, '--build', build, '--parallel', jobs)
    target = build / 'CMakeFiles/qt_link_probe.dir'
    # MinGW Makefiles can emit cleanup, archive, and compiler commands on
    # separate lines. Only the compiler command supplies linker flags.
    commands = [expand_response_files(shlex.split(line), build)
                for line in (target / 'link.txt').read_text().splitlines() if line.strip()]
    links = [command for command in commands if '-o' in command]
    if len(links) != 1:
        raise ValueError('Expected exactly one compiler link command in link.txt')
    link = links[0]
    # CMake's MinGW workaround packs all probe objects into objects.a. Expand
    # that archive back to its inputs so main() can be excluded while keeping
    # Qt plugin initialization objects.
    archives = {command[2]: command[3:] for command in commands
                if len(command) > 3 and command[1] == 'qc'}
    link = [item for token in link for item in archives.get(token, [token])]
    output = link.index('-o')
    # Preserve Qt-generated plugin initialization objects, but not probe main().
    # Libtool moves shared libraries before static archives. Keep those
    # dependencies loaded even when their consumers appear later.
    flags = ['-Wl,--no-as-needed'] if not host else []
    for i, token in enumerate(link[1:], 1):
        if i in (output, output + 1) or token.endswith(('/main.cpp.o', '/main.cpp.obj')):
            continue
        if token.startswith(('-O', '-D', '-Wl,--dependency-file=', '-Wl,--out-implib,')):
            continue
        if token.endswith(('.o', '.obj')) and not Path(token).is_absolute():
            token = str(build / token)
        flags.append(token)
    makeflags = (target / 'flags.make').read_text()
    cflags = []
    for key in ('CXX_DEFINES', 'CXX_INCLUDES'):
        cflags += shlex.split(re.search(r'^' + key + r' = (.*)$', makeflags, re.M).group(1))
    cflags = expand_response_files(cflags, build)
    # Autotools also passes these flags to moc, which accepts -I, not -isystem.
    raw_cflags = iter(cflags)
    cflags = []
    for flag in raw_cflags:
        if flag in ('-isystem', '-I'):
            cflags.append('-I' + next(raw_cflags))
        elif not flag.startswith('-DQT_TESTCASE_'):
            cflags.append(flag)
    version = re.search(r'^\$\(package\)_version=(\S+)$',
                        (ROOT / 'depends/packages/qt.mk').read_text(), re.M).group(1)
    pcdir = prefix / 'lib/pkgconfig'
    pcdir.mkdir(exist_ok=True)
    tools_prefix = prefix / 'native' if host else prefix
    for module in ('Core', 'Gui', 'Widgets', 'Network', 'Core5Compat', 'Test'):
        # Put the complete link graph on Core once; duplicate plugin objects
        # across module flags would define initialization symbols twice.
        libs = shlex.join(flags) if module == 'Core' else ''
        (pcdir / f'Qt6{module}.pc').write_text(
            f'prefix={prefix}\nyerbas_static_link=1\nlibexecdir={tools_prefix}/libexec\nbindir={tools_prefix}/bin\n'
            f'Name: Qt6 {module}\nDescription: Static Qt for Yerbas\nVersion: {version}\n'
            f'Libs: {libs}\nCflags: {shlex.join(cflags)}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--cmake', required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--static-linux', action='store_true', help='Embed Qt and its plugins on Linux')
    parser.add_argument('--windows-host', help='Resolve an existing static MinGW Qt prefix')
    parser.add_argument('--metadata-only', action='store_true', help='Resolve an already built static Qt prefix')
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    if args.static_linux and not sys.platform.startswith('linux'):
        parser.error('--static-linux requires Linux')
    if args.windows_host and not args.metadata_only:
        parser.error('--windows-host requires --metadata-only')
    if args.metadata_only:
        if not args.static_linux and not args.windows_host:
            parser.error('--metadata-only requires --static-linux or --windows-host')
        static_metadata(prefix, args.cmake, args.jobs, args.windows_host)
        return
    sources = ROOT / 'depends/sources'
    work = ROOT / ('qt-native-static-work' if args.static_linux else 'qt-native-work')
    sources.mkdir(parents=True, exist_ok=True)
    common = ['-G', 'Unix Makefiles', f'-DCMAKE_INSTALL_PREFIX={prefix}',
              f'-DCMAKE_PREFIX_PATH={prefix}', f'-DCMAKE_INSTALL_RPATH={prefix}/lib',
              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_LIBDIR=lib',
              f'-DBUILD_SHARED_LIBS={"OFF" if args.static_linux else "ON"}', '-DQT_BUILD_TESTS=OFF', '-DQT_BUILD_EXAMPLES=OFF']
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
    if args.static_linux:
        static_metadata(prefix, args.cmake, args.jobs)
    (prefix / '.complete').write_text('static-linux\n' if args.static_linux else 'shared\n')


if __name__ == '__main__':
    main()
