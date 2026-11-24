package=native_ninja
$(package)_version=1.12.1
$(package)_download_path=https://codeload.github.com/ninja-build/ninja/tar.gz/refs/tags
$(package)_download_file=v$($(package)_version)
$(package)_file_name=ninja-$($(package)_version).tar.gz
$(package)_sha256_hash=821bdff48a3f683bc4bb3b6f0b5fe7b2d647cf65d52aeb63328c91a6c6df285a

define $(package)_build_cmds
  CXX="$(build_CXX)" python3 configure.py --bootstrap
endef

define $(package)_stage_cmds
  mkdir -p $($(package)_staging_prefix_dir)/bin && \
  cp ninja $($(package)_staging_prefix_dir)/bin/
endef
