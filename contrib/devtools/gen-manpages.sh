#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
TOPDIR=${TOPDIR:-$(git rev-parse --show-toplevel)}
BUILDDIR=${BUILDDIR:-$TOPDIR}
BINDIR=${BINDIR:-$BUILDDIR/src}
MANDIR=${MANDIR:-$TOPDIR/doc/man}
BITCOIND=${BITCOIND:-$BINDIR/yerbasd}
BITCOINCLI=${BITCOINCLI:-$BINDIR/yerbas-cli}
BITCOINTX=${BITCOINTX:-$BINDIR/yerbas-tx}
BITCOINQT=${BITCOINQT:-$BINDIR/qt/yerbas-qt}
HELP2MAN=${HELP2MAN:-help2man}

for cmd in "$BITCOIND" "$BITCOINCLI" "$BITCOINTX" "$BITCOINQT"; do
  [[ -x "$cmd" ]] || { echo "$cmd not found or not executable." >&2; exit 1; }
done
# Use -help: the transaction utility does not implement --version.
# Reject mixed-version binaries instead of relabelling stale help as a new release.
version=$({ "$BITCOINCLI" -help; } | sed -n '1s/.*version v\([0-9.]*\).*/\1/p')
[[ -n "$version" ]] || { echo "Cannot determine client version" >&2; exit 1; }
for cmd in "$BITCOIND" "$BITCOINCLI" "$BITCOINTX" "$BITCOINQT"; do
  actual=$("$cmd" -help | sed -n '1s/.*version v\([0-9.]*\).*/\1/p')
  [[ "$actual" == "$version" ]] || { echo "Version mismatch: $cmd ($actual != $version)" >&2; exit 1; }
done
mkdir -p "$MANDIR"
footer=$(mktemp)
trap 'rm -f "$footer"' EXIT
printf '[COPYRIGHT]\n' > "$footer"
"$BITCOIND" --version | sed -n '1!p' >> "$footer"
for cmd in "$BITCOIND" "$BITCOINCLI" "$BITCOINTX" "$BITCOINQT"; do
  cmdname=${cmd##*/}
  "$HELP2MAN" -N --help-option=-help --version-string="$version" \
    --include="$footer" -o "$MANDIR/$cmdname.1" "$cmd"
done
