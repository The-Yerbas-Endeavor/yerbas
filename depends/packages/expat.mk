package=expat
$(package)_version=2.9.0
$(package)_download_path=https://github.com/libexpat/libexpat/releases/download/R_$(subst .,_,$($(package)_version))/
$(package)_file_name=$(package)-$($(package)_version).tar.xz
$(package)_sha256_hash=1e6371862cc31999b368c3b89b49994f0677e1bab5f1b2b85ae3741f5d803051

define $(package)_set_vars
$(package)_config_opts=--disable-shared --without-docbook --without-tests --without-examples
$(package)_config_opts += --disable-dependency-tracking --enable-option-checking --without-xmlwf
$(package)_config_opts_linux=--with-pic
endef

define $(package)_config_cmds
  $($(package)_autoconf)
endef

define $(package)_build_cmds
  $(MAKE)
endef

define $(package)_stage_cmds
  $(MAKE) DESTDIR=$($(package)_staging_dir) install
endef

define $(package)_postprocess_cmds
  rm -rf share lib/cmake lib/*.la
endef
