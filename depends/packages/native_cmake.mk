package=native_cmake
$(package)_version=4.4.4
$(package)_download_path=https://github.com/Kitware/CMake/releases/download/v$($(package)_version)
$(package)_file_name=cmake-$($(package)_version).tar.gz
$(package)_sha256_hash=bd24c30d80a7744ae84b845ff080cc8453b06c622ef01066564108e9cefc44cf

define $(package)_config_cmds
  CC="$($(package)_cc)" CXX="$($(package)_cxx)" ./bootstrap --prefix=$(build_prefix) -- -DCMAKE_USE_OPENSSL=OFF
endef

define $(package)_build_cmds
  $(MAKE)
endef

define $(package)_stage_cmds
  $(MAKE) DESTDIR=$($(package)_staging_dir) install
endef
