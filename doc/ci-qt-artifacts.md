# Qt wallet CI artifacts

The `Yerbas Build and Tests` workflow builds the wallet, daemon, CLI, native unit
suites and Qt wallet tests on every platform in its matrix:

| Artifact platform | Qt source | Wallet entry point |
| --- | --- | --- |
| Ubuntu 22 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Ubuntu 24 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Ubuntu 26 x86_64 | Ubuntu Qt packages, minimum 6.8 enforced | `yerbas-build/yerbas-qt` |
| Ubuntu 24 ARM64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| macOS 15 Intel | Pinned Qt sources from depends | `yerbas-build/Yerbas-Qt.app` |
| Windows x86_64 | Pinned cross-built Qt from depends | `yerbas-build/yerbas-qt.exe` |

Download the matching `yerbas-<platform>-binaries` artifact from a successful
workflow run, then extract the versioned archive inside. Version metadata comes
from `configure.ac` and `build.properties`; the archive also records the commit
and host and includes checksums. Use the artifact matching your OS and CPU.
This matrix does not provide a native Apple Silicon build.

Ubuntu 22/24 (including ARM64) archives contain exactly three real executables in `yerbas-build/`:
`yerbas-cli`, `yerbasd`, and `yerbas-qt`. Qt and its selected plugins are linked
into the wallet; there is no Qt launcher or separate Qt runtime directory.
The binaries still use the target Ubuntu release's system C/C++ and desktop
libraries (including X11/XCB, fontconfig and xkbcommon). They are not fully
static, distribution-independent Linux binaries.

For these Ubuntu builds, `build-info.txt`, `BINARY-SHA256SUMS`, Qt license files and the archive
checksum are alongside the versioned archive in the Actions artifact, not inside
`yerbas-build/`. Release publication must preserve that metadata and licensing
material as separate assets. `BINARY-SHA256SUMS` is checked from inside the
extracted `yerbas-build/` directory. Existing published archives are unchanged
until builds from this packaging change have passed validation and are uploaded.

Ubuntu 26 retains its current system-Qt build and package layout.

The macOS application includes its Qt dependencies via `macdeployqt` and is
ad-hoc signed. It requires macOS 15 or newer on Intel and is not notarized or
Developer ID signed. Its archive contains the app bundle, daemon and CLI;
metadata and license notices are kept outside that archive. Windows uses static
Qt and compiler runtimes, with only `yerbasd.exe`, `yerbas-cli.exe` and
`yerbas-qt.exe` in the binary directory. Packaging rejects non-system DLL imports;
notices and checksums remain alongside the archive.

`ci/build-native-qt.py` reads versions and SHA-256 hashes from the existing Qt
recipes in `depends/packages`; downloads must match those hashes before they
are extracted. The native Qt cache is separate for each runner platform and
invalidated when its builder or source recipes change. `QT_NATIVE_PREFIX`
selects that Qt installation in the native `USE_SYSTEM_QT=1` configure path.
On Linux, `--static-linux` uses Qt's CMake targets to resolve libraries and
static plugin initialization objects, then generates pkg-config metadata for
Autotools. This avoids guessing the transitive link order. Configure accepts
static Qt only with this generated Linux metadata. macOS keeps its shared-Qt app bundle. Windows resolves the static link metadata
with `--metadata-only --windows-host x86_64-w64-mingw32`. The pinned Core dependencies are unchanged.

Native test artifacts are tar archives to retain executable modes and library
symlinks. Test jobs run the packaged GUI test executable on each target, using
Qt's minimal platform on Linux and the native macOS platform. The local packaging
unit tests exercise relocation and missing-binary failure; they do not establish
that a real wallet builds or starts. Successful target build and test jobs are
required before treating those platform artifacts as validated.
