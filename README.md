Welcome to Yerbas 
===========================

 
Introduction
------------
YERB - The "Good Shit" coin!

WARNING! Yerbas is a work in progress...Use at your own risk!

Yerbas is a community driven, developmental, grassroots, digital currency that enables instant payments to anyone, anywhere in the world. The Yerbas Coin uses peer-to-peer technology to operate with no central authority: managing transactions and issuing money are carried out collectively by the network. Yerbas is a code fork of Bitcoin/Dash/Raptoreum and inherits current and optionally future features such as chain locks, oracles etc. The inspiration for the name Yerbas is derived from the Latin(herba) and Español(hierba) words for herb, grass, or weeds.

 We are further expanding capabilities by adding the following features:

A)	The deployment of a unique asset layer.  ---pushing you luck here, but maybe ;)

B)	Collaboration with real world vendors offering rewards and incentives to utilize Yerbas for everyday goods and services. 


License
-------

Yerbas Core is released under the terms of the MIT license. See [COPYING](COPYING) for more
information or see https://opensource.org/licenses/MIT.

Development Process
-------------------

The `master` branch is meant to be stable. Development is done in separate branches.
[Tags](https://github.com/The-Yerbas-Endeavor/yerbas/tags) are created to indicate new official,
stable release versions of Yerbas Core.

The contribution workflow is described in [CONTRIBUTING.md](CONTRIBUTING.md).

Testing
-------

Testing and code review is the bottleneck for development; we get more pull
requests than we can review and test on short notice. Please be patient and help out by testing
other people's pull requests, and remember this is a security-critical project where any mistake might cost people
lots of money.

### Automated Testing

Developers are strongly encouraged to write [unit tests](src/test/README.md) for new code, and to
submit new unit tests for old code. Unit tests can be compiled and run
(assuming they weren't disabled in configure) with: `make check`. Further details on running
and extending unit tests can be found in [/src/test/README.md](/src/test/README.md).

There are also [regression and integration tests](/test), written
in Python, that are run automatically on the build server.
These tests can be run (if the [test dependencies](/test) are installed) with: `test/functional/test_runner.py`

The Travis CI system makes sure that every pull request is built for Windows, Linux, and OS X, and that unit/sanity tests are run automatically.

### Manual Quality Assurance (QA) Testing

Changes should be tested by somebody other than the developer who wrote the
code. This is especially important for large or high-risk changes. It is useful
to add a test plan to the pull request description if testing the changes is
not straightforward.
