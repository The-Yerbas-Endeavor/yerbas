package=protobuf
$(package)_version=$(native_$(package)_version)
$(package)_download_path=$(native_$(package)_download_path)
$(package)_file_name=$(native_$(package)_file_name)
$(package)_sha256_hash=$(native_$(package)_sha256_hash)
$(package)_dependencies=native_$(package)

define $(package)_set_vars
  $(package)_cxxflags+=-std=c++17
  $(package)_config_opts=--disable-shared --without-zlib --with-protoc=$(build_prefix)/bin/protoc
  $(package)_config_opts_linux=--with-pic
endef

define $(package)_config_cmds
  $($(package)_autoconf)
endef

define $(package)_build_cmds
  $(MAKE) -C src libprotobuf.la
endef

define $(package)_stage_cmds
  $(MAKE) -C src DESTDIR=$($(package)_staging_dir) install-nobase_includeHEADERS && \
  $(MAKE) DESTDIR=$($(package)_staging_dir) install-pkgconfigDATA && \
  mkdir -p $($(package)_staging_prefix_dir)/lib && \
  cp src/.libs/libprotobuf.a $($(package)_staging_prefix_dir)/lib/
endef

define $(package)_postprocess_cmds
  rm -f lib/pkgconfig/protobuf-lite.pc
endef
