Yerbas Core
==========

This is the official reference wallet for Yerbas digital currency and comprises the backbone of the Yerbas peer-to-peer network. You can [download Yerbas Core](https://www.yerbas.org/downloads/) or [build it yourself](#building) using the guides below.

Running
---------------------
The following are some helpful notes on how to run Yerbas on your native platform.

### Unix

Unpack the files into a directory and run:

- `bin/yerbas-qt` (GUI) or
- `bin/yerbasd` (headless)

### Windows

Unpack the files into a directory, and then run yerbas-qt.exe.

### OS X

Drag Yerbas-Qt to your applications folder, and then run Yerbas-Qt.

### Need Help?

* See the [Yerbas documentation](https://docs.yerbas.org)
for help and more information.
* See the [Yerbas Developer Documentation](https://yerbas-docs.github.io/) 
for technical specifications and implementation details.
* Ask for help on [Yerbas Nation Discord](http://yerbaschat.org)
* Ask for help on the [Yerbas Forum](https://yerbas.org/forum)

Building
---------------------
The following are developer notes on how to build Yerbas Core on your native platform. They are not complete guides, but include notes on the necessary libraries, compile flags, etc.

- [OS X Build Notes](build-osx.md)
- [Unix Build Notes](build-unix.md)
- [Windows Build Notes](build-windows.md)
- [OpenBSD Build Notes](build-openbsd.md)
- [Gitian Building Guide](gitian-building.md)

Development
---------------------
The Yerbas Core repo's [root README](/README.md) contains relevant information on the development process and automated testing.

- [Developer Notes](developer-notes.md)
- [Release Notes](release-notes.md)
- [Release Process](release-process.md)
- Source Code Documentation ***TODO***
- [Translation Process](translation_process.md)
- [Translation Strings Policy](translation_strings_policy.md)
- [Travis CI](travis-ci.md)
- [Unauthenticated REST Interface](REST-interface.md)
- [Shared Libraries](shared-libraries.md)
- [BIPS](bips.md)
- [Dnsseed Policy](dnsseed-policy.md)
- [Benchmarking](benchmarking.md)

### Resources
* Discuss on the [Yerbas Forum](https://yerbas.org/forum), in the Development & Technical Discussion board.
* Discuss on [Yerbas Nation Discord](http://yerbaschat.org)

### Miscellaneous
- [Assets Attribution](assets-attribution.md)
- [Files](files.md)
- [Fuzz-testing](fuzzing.md)
- [Reduce Traffic](reduce-traffic.md)
- [Tor Support](tor.md)
- [Init Scripts (systemd/upstart/openrc)](init.md)
- [ZMQ](zmq.md)

License
---------------------
Distributed under the [MIT software license](/COPYING).
This product includes software developed by the OpenSSL Project for use in the [OpenSSL Toolkit](https://www.openssl.org/). This product includes
cryptographic software written by Eric Young ([eay@cryptsoft.com](mailto:eay@cryptsoft.com)), and UPnP software written by Thomas Bernard.
