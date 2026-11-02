#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT
cd "$build"
qmake6 "$root/contrib/yerbas-ai/tests/qt/page_test.pro"
make -j2
export QT_QPA_PLATFORM=offscreen
./page_test missingAndModifiedPackageRejected unexpectedCodeRejected \
  historyAndExactJobStop invalidAndSymlinkSessionRejected rewardSnapshotValidation \
  automaticStatusDoesNotOverlap rewardRequestWireAndDuplicate lifecycleDisplayValidation \
  providerStopRetriesSameIdAndRejectsWrongJob preassignedSubmissionWire preparedJobValidation
