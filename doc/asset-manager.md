# Qt Asset Manager

The Asset Manager sidebar entry groups the existing wallet asset functions into
My Assets, Send, Create, Reissue, and Restricted controls tabs. It uses the selected
wallet's asset model and the existing transaction creation and confirmation flows.
No consensus rules or asset formats are changed.

My Assets provides a case-insensitive name search, wallet quantities, administrative
ownership status, and details/metadata access. Search changes and model resets clear
selection so an action cannot silently target a different asset. Metadata retrieval
remains an explicit action in the existing details dialog.

Asset history opens the wallet transaction page with issuance, reissuance, incoming
asset transfers, and outgoing asset transfers selected. Other visible history filters
(such as date and minimum amount) remain in effect. This is wallet history, not a
network-wide index of every asset or administrative event.

Backup and recovery explains wallet backups, restore/rescan, and separate storage
for referenced metadata, with a button to invoke the existing wallet backup dialog.

## Local validation

The Qt AssetViewTests suite covers search and sorting, selection invalidation,
ownership-token display, selected-asset dispatch, model resets and wallet model
replacement, alongside the existing metadata tests.

Manual smoke checks for a disposable wallet:

- Open Asset Manager and visit all five tabs; confirm sidebar selection stays on
  Asset Manager and existing forms remain usable at the minimum window size.
- Select an asset, open details, then select Send; verify the exact asset name in
  the existing transfer form before confirming any transaction.
- Use Overview asset context actions for Send, Create sub/unique asset, and Reissue;
  confirm the corresponding Asset Manager tab opens with the intended asset.
- Change the search, refresh balances, and switch wallets; confirm there is no
  stale selection or balance carried between wallets.
- Open Asset history and confirm the asset transaction filter is selected.
- Open Backup and recovery, cancel, then invoke backup and cancel its file dialog.

QR transfer parsing, hardware-wallet signing, external asset directories, and smart
contracts are not implemented by this UI change.
