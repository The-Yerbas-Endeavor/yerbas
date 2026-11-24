#!/usr/bin/env python3
"""Build native desktop Qt from the same verified sources as Windows depends."""
import argparse
import hashlib
import os
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


# These Linux ABI libraries are supplied by the destination OS.
LINUX_SYSTEM_LIBRARIES = re.compile(
    r'^(?:ld-linux[^/]*\.so(?:\.\d+)*|'
    r'lib(?:c|m|dl|pthread|rt|resolv|gcc_s|stdc\+\+|atomic)\.so(?:\.\d+)*)$'
)
DESKTOP_MODULES = (
    'x11-xcb', 'x11', 'xkbcommon-x11', 'xcb-cursor', 'xcb-icccm', 'xcb-image',
    'xcb-keysyms', 'xcb-randr', 'xcb-renderutil', 'xcb-shm', 'xcb-sync',
    'xcb-xfixes', 'xcb-render', 'xcb-shape', 'xcb-xkb', 'xcb-util', 'xcb',
    'xdmcp', 'fontconfig', 'libbrotlidec',
)


def linux_static_desktop_link(link, prefix, build, staging_prefix, target_pc=None):
    """Resolve the desktop archive closure and test it with the actual Qt probe."""
    env = os.environ.copy()
    env.pop('PKG_CONFIG_LIBDIR', None)
    env['PKG_CONFIG_PATH'] = str(prefix / 'lib/pkgconfig')
    if target_pc:
        env['PKG_CONFIG_PATH'] = ''
        env['PKG_CONFIG_LIBDIR'] = target_pc
        env.pop('PKG_CONFIG_SYSROOT_DIR', None)
    compiler = shlex.split(os.environ['CXX']) if target_pc else [link[0]]
    libraries = shlex.split(subprocess.check_output(
        ['pkg-config', '--static', '--libs', *DESKTOP_MODULES], text=True, env=env
    ))
    search_dirs = [prefix / 'lib', *(Path(flag[2:]) for flag in libraries if flag.startswith('-L'))]
    archives = {}

    for flag in libraries:
        if flag.startswith('-L') or flag == '-pthread':
            continue
        if not flag.startswith('-l'):
            raise ValueError(f'Unexpected desktop pkg-config link option: {flag}')
        name = flag[2:]
        if LINUX_SYSTEM_LIBRARIES.fullmatch(f'lib{name}.so'):
            continue
        archive = f'lib{name}.a'
        for directory in search_dirs:
            if (directory / archive).is_file():
                archives[name] = str(directory / archive)
                break
        else:
            path = subprocess.check_output([*compiler, f'-print-file-name={archive}'], text=True).strip()
            if not Path(path).is_absolute() or not Path(path).is_file():
                raise ValueError(f'Missing static desktop archive: {archive}. Install its development package on the builder.')
            archives[name] = os.path.realpath(path)

    # Libtool moves standalone -Wl options ahead of the archives. Keep the
    # group in a linker script that it passes as a single archive input.
    group = staging_prefix / 'lib/yerbas-qt/libyerbas-desktop.a'
    group.parent.mkdir(parents=True, exist_ok=True)
    members = [
        f'-l:{Path(path).name}' if Path(path).parent == prefix / 'lib' else f'"{path}"'
        for path in archives.values()
    ]
    group.write_text('/* GNU ld script */\nGROUP ( ' + ' '.join(members) + ' )\n')
    result = []
    for item in link:
        match = re.fullmatch(r'(?:.*/)?lib(.+?)\.so(?:\.\d+)*', item)
        if (match and match[1] in archives) or (item.startswith('-l') and item[2:] in archives):
            continue
        result.append(item)
    result += [f'-L{prefix}/lib', str(group)]
    subprocess.run(result, cwd=build, check=True)
    return result


def check_linux_elf(path, architecture=None):
    if architecture:
        expected = {'i686': (1, 3), 'aarch64': (2, 183)}[architecture]
        with path.open('rb') as executable:
            header = executable.read(20)
        if (len(header) != 20 or header[:4] != b'\x7fELF' or header[5] != 1 or
                (header[4], int.from_bytes(header[18:20], 'little')) != expected):
            raise ValueError(f'{path}: expected a little-endian {architecture} ELF')
        symbols = subprocess.check_output(['readelf', '-sW', path], text=True)
        if not re.search(r'\bFUNC\s+\S+\s+\S+\s+\d+\s+\S*qt_static_plugin_QXcbIntegrationPlugin', symbols):
            raise ValueError(f'{path}: static XCB platform plugin not found')
    dynamic = subprocess.check_output(['readelf', '-dW', path], text=True)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic)
    unexpected = [name for name in needed if not LINUX_SYSTEM_LIBRARIES.fullmatch(name)]
    if not needed or unexpected or re.search(r'\((?:RPATH|RUNPATH)\)', dynamic):
        raise ValueError(f'{path}: unexpected ELF runtime dependencies or search path: {unexpected}')


def static_metadata(prefix, cmake, jobs, host=None, staging_prefix=None, probe_dir=None,
                    linux_host=None, target_pc=None, cmake_args=()):
    """Resolve static plugins with Qt's CMake targets for our Autotools build."""
    probe = probe_dir or prefix / 'static-link'
    output_prefix = staging_prefix or prefix
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
    if staging_prefix:
        cross_args += [f'-DQt6Core5Compat_DIR={staging_prefix}/lib/cmake/Qt6Core5Compat',
                       f'-DCMAKE_MODULE_PATH={staging_prefix}/lib/cmake/Qt6']
        if not host:
            cross_args += [f'-DOPENSSL_ROOT_DIR={prefix}', '-DOPENSSL_USE_STATIC_LIBS=ON']
    run(cmake, '-S', probe, '-B', build, '-G', 'Unix Makefiles',
        f'-DCMAKE_PREFIX_PATH={prefix}', '-DCMAKE_BUILD_TYPE=Release', *cross_args, *cmake_args)
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
    if staging_prefix and not host:
        link = linux_static_desktop_link(link, prefix, build, staging_prefix, target_pc)
        check_linux_elf(build / link[link.index('-o') + 1], linux_host)
    output = link.index('-o')
    # Preserve Qt-generated plugin initialization objects, but not probe main().
    # Libtool moves shared libraries before static archives. Keep those
    # dependencies loaded even when their consumers appear later.
    flags = ['-Wl,--no-as-needed'] if not host and not staging_prefix else []
    plugin_objects = output_prefix / 'lib/yerbas-qt'
    for i, token in enumerate(link[1:], 1):
        if i in (output, output + 1) or token.endswith(('/main.cpp.o', '/main.cpp.obj')):
            continue
        if token.startswith(('-O', '-D', '-Wl,--dependency-file=', '-Wl,--out-implib,')):
            continue
        if token.endswith(('.o', '.obj')) and not Path(token).is_absolute():
            token = str(build / token)
        if staging_prefix and token.endswith(('.o', '.obj')):
            plugin_objects.mkdir(parents=True, exist_ok=True)
            source = Path(token)
            # CMake's imports can share basenames across plugin types.
            name = f'{i}-{source.name}'
            shutil.copy2(source, plugin_objects / name)
            token = f'${{prefix}}/lib/yerbas-qt/{name}'
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
    pcdir = output_prefix / 'lib/pkgconfig'
    pcdir.mkdir(exist_ok=True)
    if staging_prefix:
        # The depends cache is reusable after moving the checkout.
        def relocate(tokens):
            return [
                token.replace(str(staging_prefix) + '/', '${prefix}/')
                     .replace(str(prefix) + '/', '${prefix}/')
                for token in tokens
            ]
        flags = relocate(flags)
        cflags = relocate(cflags)
    pc_prefix = '${pcfiledir}/../..' if staging_prefix else str(prefix)
    tools_prefix = '${prefix}/native' if host or linux_host else '${prefix}'
    for module in ('Core', 'Gui', 'Widgets', 'Network', 'Core5Compat', 'Test'):
        # Put the complete link graph on Core once; duplicate plugin objects
        # across module flags would define initialization symbols twice.
        libs = shlex.join(flags) if module == 'Core' else ''
        (pcdir / f'Qt6{module}.pc').write_text(
            f'prefix={pc_prefix}\nyerbas_static_link=1\nlibexecdir={tools_prefix}/libexec\nbindir={tools_prefix}/bin\n'
            f'Name: Qt6 {module}\nDescription: Static Qt for Yerbas\nVersion: {version}\n'
            f'Libs: {libs}\nCflags: {shlex.join(cflags)}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-linux-elf', type=Path, help='Verify the final raw Linux wallet ELF')
    parser.add_argument('--prefix', type=Path)
    parser.add_argument('--cmake')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--static-linux', action='store_true', help='Embed Qt and its plugins on Linux')
    parser.add_argument('--windows-host', help='Resolve an existing static MinGW Qt prefix')
    parser.add_argument('--metadata-only', action='store_true', help='Resolve an already built static Qt prefix')
    parser.add_argument('--staging-prefix', type=Path, help='Emit relocatable metadata in a depends staging prefix')
    parser.add_argument('--probe-dir', type=Path, help='Build directory for the static plugin link probe')
    parser.add_argument('--linux-host', choices=['i686', 'aarch64'],
                        help='Verify a cross-compiled ELF and select native Qt tools')
    parser.add_argument('--target-pkg-config-libdir', help='Target pkg-config search directories')
    parser.add_argument('--cmake-arg', action='append', default=[], help='Argument for the link probe')
    args = parser.parse_args()
    if args.check_linux_elf:
        check_linux_elf(args.check_linux_elf, args.linux_host)
        return
    if not args.prefix or not args.cmake:
        parser.error('--prefix and --cmake are required for Qt builds or metadata generation')
    prefix = args.prefix.resolve()
    if args.static_linux and not sys.platform.startswith('linux'):
        parser.error('--static-linux requires Linux')
    if args.windows_host and not args.metadata_only:
        parser.error('--windows-host requires --metadata-only')
    if (args.staging_prefix or args.probe_dir) and not (
        args.metadata_only and (args.static_linux or args.windows_host)
    ):
        parser.error('--staging-prefix and --probe-dir require static Qt metadata generation')
    if (args.linux_host or args.target_pkg_config_libdir or args.cmake_arg) and not (
        args.static_linux and args.metadata_only and args.staging_prefix
        and args.linux_host and args.target_pkg_config_libdir and args.cmake_arg
        and 'CC' in os.environ and 'CXX' in os.environ
    ):
        parser.error('Linux cross metadata requires staged Qt, target pkg-config paths, CMake arguments and CC/CXX')
    if args.metadata_only:
        if not args.static_linux and not args.windows_host:
            parser.error('--metadata-only requires --static-linux or --windows-host')
        static_metadata(prefix, args.cmake, args.jobs, args.windows_host,
                        args.staging_prefix, args.probe_dir, args.linux_host,
                        args.target_pkg_config_libdir, args.cmake_arg)
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
