# Qt host tools and Windows libraries must use the same source version.
package=native_qttools
$(package)_version=6.12.0
$(package)_download_path=https://download.qt.io/official_releases/qt/6.12/$($(package)_version)/submodules
$(package)_file_name=qttools-everywhere-src-$($(package)_version).tar.xz
$(package)_sha256_hash=8dab8f3611496486a470ad5f115ceea584f36bc22a2b8b6f6ebdbafbb8160693
$(package)_dependencies=native_qt

define $(package)_config_cmds
  $(build_prefix)/bin/cmake -S . -B build -G "Unix Makefiles" \
    -DCMAKE_INSTALL_PREFIX=$(build_prefix) \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DQT_BUILD_TESTS=OFF \
    -DQT_BUILD_EXAMPLES=OFF \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_C_COMPILER="$(build_CC)" \
    -DCMAKE_CXX_COMPILER="$(build_CXX)" \
    -DCMAKE_PREFIX_PATH=$(build_prefix) \
    -DFEATURE_assistant=OFF \
    -DFEATURE_designer=OFF \
    -DFEATURE_qdoc=OFF \
    -DFEATURE_clang=OFF \
    -DFEATURE_distancefieldgenerator=OFF \
    -DFEATURE_pixeltool=OFF \
    -DFEATURE_qdbus=OFF \
    -DFEATURE_qtdiag=OFF \
    -DFEATURE_qtplugininfo=OFF \
    -DFEATURE_kmap2qmap=OFF \
    -DFEATURE_linguist=ON
endef

define $(package)_build_cmds
  $(MAKE) -C build
endef

define $(package)_stage_cmds
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/cmake --install build
endef
