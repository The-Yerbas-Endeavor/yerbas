#!/bin/sh
# Copyright (c) 2013-2016 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export LC_ALL=C
set -e
srcdir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$srcdir"

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "configuration failed, please install $2 and re-run autogen.sh" >&2
    exit 1
  fi
}

if [ -z "${LIBTOOLIZE}" ] && GLIBTOOLIZE="$(command -v glibtoolize 2>/dev/null)"; then
  LIBTOOLIZE="${GLIBTOOLIZE}"
  export LIBTOOLIZE
fi

: "${AUTORECONF:=autoreconf}"
: "${AUTOCONF:=autoconf}"
: "${AUTOMAKE:=automake}"
: "${ACLOCAL:=aclocal}"
export AUTOCONF AUTOMAKE ACLOCAL
require_tool "$AUTORECONF" autoconf
require_tool "$AUTOCONF" autoconf
require_tool "$AUTOMAKE" automake
require_tool "$ACLOCAL" automake
if [ -z "${PKG_CONFIG}" ]; then
  if command -v pkg-config >/dev/null 2>&1; then
    PKG_CONFIG=pkg-config
  else
    PKG_CONFIG=pkgconf
  fi
fi
require_tool "$PKG_CONFIG" 'pkg-config (or pkgconf)'
export PKG_CONFIG

if [ -n "${LIBTOOLIZE}" ]; then
  require_tool "${LIBTOOLIZE}" libtool
else
  require_tool libtoolize libtool
fi

exec "$AUTORECONF" --install --force --warnings=all "$@"
