> Dependency/configure notes below describe the original asset-viewer batch.
> The later [Qt 6 migration](local-gui-build.md) supersedes its Qt/protobuf
> requirements: protobuf and the protoc probe have been removed.

# Asset viewer, audit fixes, and configure updates

Prepared on `dev`, based on b20adb4aa1613cbbfc9ef7155d9c5e98c8e61a5b. They extend the dependency work documented in [dependency-updates.md](dependency-updates.md) and [local-gui-build.md](local-gui-build.md).

## Raptoreum comparison and implemented features

Reference: [Raptor3um/raptoreum, src/qt/assetsdialog.cpp](https://github.com/Raptor3um/raptoreum/blob/master/src/qt/assetsdialog.cpp), reviewed from its master branch. Raptoreum offers metadata details, supply/type information, and reference-image previews. Its full-image method is marked TODO in the reviewed source. This implementation is newly written for Yerbas's existing name-based asset metadata and owner tokens; it does not import Raptoreum's asset IDs, mint transactions, or consensus rules.

In Yerbas Overview, double-click an asset or select **View asset details** in its context menu. A read-only snapshot displays the asset name, type, wallet quantity, administrator status, metadata asset name, total supply, decimal places, reissuability, and content reference. Owner-token rows resolve metadata from the underlying asset. Missing metadata is explicitly reported.

**Load image preview** fetches content asynchronously using the wallet's configured SOCKS proxy (or direct access if no proxy is configured). Merely opening details makes no request. Preview limits are 8 MiB, 15 seconds, and 16 million decoded pixels. PNG/JPEG/GIF/WebP are accepted when a decoder is available; animation displays as a still image. Redirects are rejected. Errors leave the metadata available and allow retry. **View full-size image** opens a scrollable viewer. Closing details cancels requests. Content is gateway-supplied and is not cryptographically verified against the CID by this viewer.

The existing **Open IPFS in Browser** action now works and retains its confirmation prompt. The external browser uses its own network settings. Only CIDv0 references and valid HTTP(S) gateway templates with exactly one `%s` placeholder are accepted; transaction-hash references remain viewable/copyable text. `strIpfsUrl` is initialized from Qt settings, with `https://ipfs.io/ipfs/%s` as the default. There is no new gateway preferences control in this change.

Raptoreum's separate confirmed/pending columns and asset mint/update workflows have not been ported: Yerbas continues to display its existing available asset balance semantics. This is a viewer adaptation, not complete feature parity.

## Errors found and fixed

| Area | Previous behavior | Correction |
| --- | --- | --- |
| Wallet selection | Overview used a global helper reading `vpwallets[0]` | Query the displayed WalletModel's wallet under the chain/wallet locks |
| Missing metadata | One unavailable asset stopped the entire refresh | Preserve the balance with eight-decimal formatting and continue; details report unavailable metadata |
| Asset refresh | Replaced cached records using layout signals and an out-of-range dataChanged endpoint | Use begin/end model reset; reject invalid table parents/columns and foreign indexes |
| Stale selections | Context-menu event loop could retain an index across refresh | Track a persistent index and cancel action after invalidation |
| Administrator icon | Missing return painted an administrator icon for non-admin assets | Return an empty decoration for non-admin assets |
| Sorting | Role number 101 was passed as the sort column | Set the name role and sort column zero ascending, ignoring case |
| Filtering | Contains filter bypassed prefix filter | Apply both predicates, ignoring case |
| Quantity formatting | Floating-point divisor; signed overflow for INT64_MIN | Integer-only decimal reduction, safe unsigned magnitude, bounded 0–8 display decimals |
| Browser action | Opening commands were commented out; gateway string never initialized | Initialize gateway, validate URLs, confirm and open; report browser launch failure |
| Restricted records | Watch-only flag had no default value | Initialize false; preserve/compute known wallet ownership |
| Restricted model | Unchecked database pointer and table indexes; updates lacked notification | Guard missing database/wallet, lock ownership reads, validate bounds, use current row records, emit dataChanged |
| Overview build | QPainterPath relied on transitive includes | Include QPainterPath directly |

Changed production files: `src/qt/assetdetailsdialog.{h,cpp}` (new), `assetfilterproxy.cpp`, `assetrecord.h`, `assettablemodel.cpp`, `myrestrictedassetrecord.h`, `myrestrictedassettablemodel.cpp`, `optionsmodel.cpp`, `overviewpage.{h,cpp}`, and `src/Makefile.qt.include`.

## Configure changes

`configure.ac` now requires Boost 1.70 or newer (depends pins 1.90), Qt 5.9 or newer (native local build uses 5.15.18), OpenSSL 1.1.1 or newer (depends pins 3.5.9), and protobuf 3.20.3 or newer (depends pins 3.20.3). Minimums describe compatibility, not a recommendation to use unsupported old releases. C++17 remains required.

OpenSSL's header minimum is checked even without pkg-config. For GUI builds, configure runs the selected protoc against a tiny proto and compiles its output header against the selected protobuf headers. This catches a missing/broken generator, too-old headers, and incompatible generator/header combinations early. It is a compile check and is suitable for cross builds; it does not execute target binaries. Qt-disabled builds skip this protobuf probe. Regenerate configure with `./autogen.sh` before the next manual build.

## Validation performed

- New `src/qt/test/assetviewtests.{h,cpp}` is registered in `src/Makefile.qttest.include` and the Qt test runner.
- Focused offscreen Qt run: 8 results passed, zero failed/skipped (includes init/cleanup). Tests cover URL rejection, combined filters/sorting, integer formatting including INT64_MIN, metadata-only opening without a request, a successful local PNG download, and redirect rejection. No public gateway was contacted by tests.
- C++17 syntax checks against Boost 1.90, Qt 5.15.18, protobuf 3.20.3 and OpenSSL 3.5.9 headers passed for the new viewer, asset model/filter, overview, options, and the existing asset dialogs/models.
- All nine `src/assets/*.cpp` translation units passed syntax checks. This is compilation coverage, not a consensus or database correctness proof. No core asset serialization, activation rules, public consensus parameters, wallet formats, or transaction validation rules were changed.
- Autoconf generation, generated shell syntax, and diff whitespace checks pass. The extracted production protobuf configure probe accepts matching 3.20.3 tools/headers and rejects a failed protoc.

The focused checks do not establish a successful full application link, live-node asset correctness, cross-platform success, or repair of the earlier legacy unit-suite failures. A full GUI build, wallet switching/reorg testing, and live issuance/transfer/reissue tests remain pending. No expensive full build was started.

## Manual validation after building

Use the commands in [local-gui-build.md](local-gui-build.md), then run all enabled unit suites and the Qt test executable. On a disposable regtest wallet, verify root/sub/unique/owner-only assets, unavailable metadata, and multiple loaded wallets. Verify issuing/transferring/reissuing still works, balances refresh after mining/reorgs, restricted-tag/freeze updates repaint, and each displayed wallet shows its own holdings. Check details, copy actions, search, preview failure/retry, full-size scrolling, and closing while loading. A gateway requiring redirects should report an error rather than silently follow it.

The previous 71-suite run remains a historical result from the older binary; this change does not relabel it as passing.

## Build version 4.0.0.1

Updated `configure.ac` client version components from 3.2.0.21 to 4.0.0.1 and included the build component in Autoconf's package version. Updated snapshot, release, and candidate versions in `build.properties`. Windows version resources and macOS plist templates already consume these version components. The encoded client version is now 4000001. The network protocol version and historical parameter-download release URL are unchanged.

Autoconf generation and `configure --version` confirm 4.0.0.1. Existing binaries and generated configuration headers still reflect the earlier build until `./autogen.sh`, configure, and the manual build are run. No release tag or publication was created.
