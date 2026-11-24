package=native_bison
$(package)_version=3.8.2
$(package)_download_path=https://ftp.gnu.org/gnu/bison
$(package)_file_name=bison-$($(package)_version).tar.xz
$(package)_sha256_hash=9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2

define $(package)_config_cmds
  $($(package)_autoconf) --disable-nls
endef

define $(package)_build_cmds
  $(MAKE)
endef

define $(package)_stage_cmds
  $(MAKE) DESTDIR=$($(package)_staging_dir) install
endef
