package=native_protobuf
$(package)_version=3.20.3
$(package)_download_path=https://github.com/protocolbuffers/protobuf/releases/download/v$($(package)_version)
$(package)_file_name=protobuf-cpp-$($(package)_version).tar.gz
$(package)_sha256_hash=e51cc8fc496f893e2a48beb417730ab6cbcb251142ad8b2cd1951faa5c76fe3d

define $(package)_set_vars
$(package)_config_opts=--disable-shared --without-zlib
endef

define $(package)_config_cmds
  $($(package)_autoconf)
endef

define $(package)_build_cmds
  $(MAKE) -C src protoc
endef

define $(package)_stage_cmds
  $(MAKE) -C src DESTDIR=$($(package)_staging_dir) install-binPROGRAMS
endef

define $(package)_postprocess_cmds
  rm -rf lib include
endef
