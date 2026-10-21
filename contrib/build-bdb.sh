#!/bin/sh
# Build the wallet-compatible Berkeley DB locally; never install system packages.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
prefix=${1:-"$repo/depends/bdb"}
case "$prefix" in /*) ;; *) prefix="$PWD/$prefix" ;; esac
jobs=${JOBS:-2}
case "$jobs" in ''|*[!0-9]*|0) echo 'JOBS must be a positive integer' >&2; exit 1 ;; esac
version=4.8.30
archive="db-$version.NC.tar.gz"
expected=12edc0df75bf9abd7f82f821795bcee50f42cb2e5f76a6a281b85732798364ef
sources="$repo/depends/sources"
mkdir -p "$sources"
if [ ! -f "$sources/$archive" ]; then
    download=$(mktemp "$sources/.bdb-download.XXXXXX")
    trap 'rm -f "$download"' EXIT HUP INT TERM
    curl --fail --location --retry 3 --output "$download" "https://download.oracle.com/berkeley-db/$archive"
    mv "$download" "$sources/$archive"
    trap - EXIT HUP INT TERM
fi
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$sources/$archive" | cut -d ' ' -f 1)
else
    actual=$(shasum -a 256 "$sources/$archive" | cut -d ' ' -f 1)
fi
if [ "$actual" != "$expected" ]; then
    echo "Checksum mismatch: $sources/$archive; remove that archive and retry." >&2
    exit 1
fi
mkdir -p "$repo/depends/work"
work=$(mktemp -d "$repo/depends/work/local-bdb.XXXXXX")
# Preserve this directory on failure for diagnostics; remove it only after success.
printf 'Building Berkeley DB %s in %s\n' "$version" "$work"
tar -xzf "$sources/$archive" -C "$work"
source="$work/db-$version.NC"
# Oracle ships read-only source files; these extracted files belong to this user.
chmod -R u+w "$source"
(cd "$source" && patch -p1 < "$repo/depends/patches/bdb/clang_cxx_11.patch")
cp "$repo/depends/config.guess" "$repo/depends/config.sub" "$source/dist/"
cd "$source/build_unix"
CC=${CC:-cc} CXX=${CXX:-c++} \
CFLAGS="${CFLAGS:--O2} -fPIC -Wno-error=implicit-function-declaration" \
CXXFLAGS="${CXXFLAGS:--O2} -fPIC -std=c++17" \
../dist/configure --prefix="$prefix" --disable-shared --enable-cxx --disable-replication
make -j"$jobs" libdb_cxx-4.8.a libdb-4.8.a
make install_lib install_include
rm -rf "$work"
printf '\nBerkeley DB 4.8 installed in %s (no sudo).\n' "$prefix"
printf 'Configure Yerbas with: ./configure --with-bdb="%s" [other options]\n' "$prefix"
