# Windows runtime components

This unsigned CI ZIP contains Yerbas Core (see COPYING), shared Qt 6.12.0 libraries
and plugins, and the MinGW runtime DLLs required by their PE import tables. Keep
the entire `bin` directory together, including `qt.conf` and `plugins`.

Qt license texts are included under `licenses/qtbase` and `licenses/qt5compat`.
Corresponding source archives and hashes are pinned in `depends/packages/qt.mk`
and `depends/packages/qt5compat.mk`. The pinned Qt archive already contains both
CVE-2026-101201 fixes. The Yerbas source commit is recorded in build-info.txt.

Sources: https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/
and https://github.com/The-Yerbas-Endeavor/yerbas .

Qt uses Windows Schannel for HTTPS, including asset images. PNG support is built
into QtGui; GIF and JPEG plugins are included. WebP is optional and is not supplied
by this QtBase-only package.

MinGW runtime DLLs come from the Ubuntu runner's compiler packages. The package
includes their installed copyright/license notices and exact package versions in
`licenses/toolchain`. Corresponding source packages are available from the Ubuntu
archive for those versions. GCC runtime libraries use GPLv3 with the GCC Runtime
Library Exception; mingw-w64 has its own component licenses.
