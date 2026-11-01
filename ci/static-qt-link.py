#!/usr/bin/env python3
"""Use Qt's CMake targets to resolve static plugins and link flags for Autotools.

Keep the output directory until the wallet and its tests have been linked: the
flags include Qt-generated plugin initialization objects from that directory.
"""
import argparse
from pathlib import Path
import shlex
import subprocess


def expand_response_files(tokens, root):
    result = []
    for token in tokens:
        if token.startswith('@'):
            result.extend(expand_response_files(shlex.split((root / token[1:]).read_text()), root))
        else:
            result.append(token)
    return result


def link_flags(command, root):
    tokens = iter(expand_response_files(shlex.split(command), root)[1:])
    result = []
    for token in tokens:
        if token == '-o':
            next(tokens)
            continue
        if token.endswith(('/probe.cpp.o', '/probe.cpp.obj')):
            continue
        if token.startswith(('-Wl,--out-implib,', '-Wl,--major-image-version,')):
            continue
        if token.endswith(('.o', '.obj', '.a')) and not token.startswith('-'):
            token = str((root / token).resolve())
        result.append(token)
    # Autotools/libtool expands these as shell words, not a shell command.
    if any(any(c.isspace() for c in token) for token in result):
        raise ValueError('Static Qt build paths must not contain whitespace')
    return ' '.join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--toolchain', type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'probe.cpp').write_text('#include <QApplication>\nint main(int argc, char **argv) { QApplication app(argc, argv); return 0; }\n')
    (root / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.22)
project(YerbasStaticQtProbe LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets Network Core5Compat Test)
get_target_property(qt_type Qt6::Core TYPE)
if(NOT qt_type STREQUAL "STATIC_LIBRARY")
  message(FATAL_ERROR "This probe requires static Qt")
endif()
foreach(name wallet wallet_test)
  add_executable(${name} probe.cpp)
  target_link_libraries(${name} PRIVATE Qt6::Widgets Qt6::Network Qt6::Core5Compat)
  qt_import_plugins(${name} INCLUDE Qt6::QMinimalIntegrationPlugin)
  if(WIN32)
    target_link_options(${name} PRIVATE -static -static-libgcc -static-libstdc++)
  endif()
endforeach()
target_link_libraries(wallet_test PRIVATE Qt6::Test)
''')
    command = [args.cmake, '-S', str(root), '-B', str(root / 'build'),
               '-G', 'Unix Makefiles', '-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_PREFIX_PATH=' + str(args.prefix.resolve())]
    if args.toolchain:
        command.append('-DCMAKE_TOOLCHAIN_FILE=' + str(args.toolchain.resolve()))
    subprocess.run(command, check=True)
    subprocess.run([args.cmake, '--build', str(root / 'build'), '--parallel', '2'], check=True)
    for name in ('wallet', 'wallet_test'):
        command = (root / 'build/CMakeFiles' / (name + '.dir/link.txt')).read_text()
        (root / (name + '.libs')).write_text(link_flags(command, root / 'build') + '\n')


if __name__ == '__main__':
    main()
