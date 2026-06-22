#!/bin/sh
# Copyright (c) 2013-2016 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export LC_ALL=C
set -e
srcdir="$(dirname "$0")"
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

require_tool autoreconf autoconf
require_tool aclocal automake

if [ -n "${LIBTOOLIZE}" ]; then
  require_tool "${LIBTOOLIZE}" libtool
else
  require_tool libtoolize libtool
fi

autoreconf --install --force --warnings=all
