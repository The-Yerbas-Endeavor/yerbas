# Qt host tools and Windows libraries must use the same source version.
package=native_qt
$(package)_version=6.12.0
$(package)_download_path=https://download.qt.io/official_releases/qt/6.12/$($(package)_version)/submodules
$(package)_file_name=qtbase-everywhere-src-$($(package)_version).tar.xz
$(package)_sha256_hash=a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307
$(package)_dependencies=native_cmake

define $(package)_config_cmds
  $(build_prefix)/bin/cmake -S . -B build -G "Unix Makefiles" \
    -DCMAKE_INSTALL_PREFIX=$(build_prefix) \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DQT_BUILD_TESTS=OFF \
    -DQT_BUILD_EXAMPLES=OFF \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_INSTALL_RPATH=$(build_prefix)/lib \
    -DCMAKE_C_COMPILER="$(build_CC)" \
    -DCMAKE_CXX_COMPILER="$(build_CXX)" \
    -DFEATURE_system_zlib=OFF \
    -DFEATURE_system_pcre2=OFF \
    -DFEATURE_system_doubleconversion=OFF \
    -DFEATURE_system_libb2=OFF \
    -DFEATURE_icu=OFF \
    -DFEATURE_zstd=OFF \
    -DFEATURE_dbus=OFF \
    -DFEATURE_sql=OFF \
    -DFEATURE_openssl=OFF \
    -DFEATURE_gui=OFF \
    -DFEATURE_widgets=OFF \
    -DFEATURE_network=OFF \
    -DFEATURE_testlib=OFF
endef

define $(package)_build_cmds
  $(MAKE) -C build
endef

define $(package)_stage_cmds
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/cmake --install build
endef
