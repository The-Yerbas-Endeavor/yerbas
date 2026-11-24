# Qt Linguist tools for the native static Linux build.
package=qttools
$(package)_version=6.12.0
$(package)_download_path=https://download.qt.io/official_releases/qt/6.12/$($(package)_version)/submodules
$(package)_file_name=qttools-everywhere-src-$($(package)_version).tar.xz
$(package)_sha256_hash=8dab8f3611496486a470ad5f115ceea584f36bc22a2b8b6f6ebdbafbb8160693
$(package)_dependencies=qt

define $(package)_config_cmds
  env -u PKG_CONFIG_LIBDIR PKG_CONFIG_PATH="$(host_prefix)/lib/pkgconfig" $(build_prefix)/bin/cmake -S . -B build -G "Unix Makefiles" \
    -DCMAKE_INSTALL_PREFIX=$(host_prefix) \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DQT_BUILD_TESTS=OFF \
    -DQT_BUILD_EXAMPLES=OFF \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_C_COMPILER="$(firstword $(host_CC))" \
    -DCMAKE_C_COMPILER_ARG1="$(wordlist 2,99,$(host_CC))" \
    -DCMAKE_CXX_COMPILER="$(firstword $(host_CXX))" \
    -DCMAKE_CXX_COMPILER_ARG1="$(wordlist 2,99,$(host_CXX))" \
    -DCMAKE_PREFIX_PATH=$(host_prefix) \
    -DOPENSSL_ROOT_DIR="$(host_prefix)" \
    -DOPENSSL_USE_STATIC_LIBS=ON \
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
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/cmake --install build && \
  mkdir -p $($(package)_staging_prefix_dir)/share/licenses/qttools && \
  cp -R LICENSES/. $($(package)_staging_prefix_dir)/share/licenses/qttools/
endef
