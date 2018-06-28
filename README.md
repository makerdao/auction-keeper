# auction-keeper

[![Build Status](https://travis-ci.org/makerdao/auction-keeper.svg?branch=master)](https://travis-ci.org/makerdao/auction-keeper)
[![codecov](https://codecov.io/gh/makerdao/auction-keeper/branch/master/graph/badge.svg)](https://codecov.io/gh/makerdao/auction-keeper)

The _DAI Stablecoin System_ incentivizes external agents, called _keepers_,
to automate certain operations around the Ethereum blockchain.

`auction-keeper` can participate in `flip` (collateral sale), `flap` (MKR buy-and-burn)
and `flop` (MKR minting) auctions. Its unique feature is the ability to plug in external
_bidding models_, which tell the keeper when and how high to bid. This keeper can be safely
left running in background. The moment it notices a new auction it will spawn a new instance
of a _bidding model_ for it and then act according to its instructions. _Bidding models_ will
be automatically terminated by the keeper the moment the auction expires.  The keeper also
automatically `deal`s expired auctions if it's us who won them.

Bear in mind that this keeper is still **early work in progress**. Many of the things described
here may still change.

<https://chat.makerdao.com/channel/keeper>


## Description

**TODO**

Bidding models are simple, external processes. They can be basically implemented in any programming language,
as the only thing they need to do is to read and write JSON documents exchanged with `auction-keeper`.


### Monitoring ongoing auctions and discovering new ones

The main task of this keeper, as already outlined above, is to constantly monitor all ongoing auctions,
discover new ones, ensure that an instance of _bidding model_ is running for each auction, provide
these instances of the current status of their auctions and bid according to decisions taken by them.

The way the auction discovery and monitoring mechanism works at the moment is pretty lame. It basically
operates as a loop which kicks in on every new block and simply enumerates all auctions from `1` to `kicks`.
Even if the _bidding model_ decides to send a bit, it will not be processed by the keeper until the next
iteration of that loop. We definitely plan to upgrade this mechanism with something smarter in the future,
especially that the current approach will stop performing well the moment the number of both current
and historical auctions will rise. The GitHub issue for it is here: <https://github.com/makerdao/auction-keeper/issues/4>.

Having said that, the current lame mechanism will probably stay around for a while as we first want
to validate the whole architecture and only start optimizing it when it becomes necessary. Ultimately,
good responsiveness of the keeper will be essential as the auctions space will become more competitive.


### Starting and stopping _bidding models_

`auction-keeper` maintains a collection of child processes, as each _bidding model_ is its own dedicated
process. New processes (new _bidding model_ instances) are spawned by executing a command according to the
`--model` commandline parameter. These processes are automatically terminated (via `SIGKILL`) by the keeper
shortly after their associated auction expires.

Whenever the _bidding model_ process dies, it gets automatically respawned by the keeper.

Example:
```bash
bin/auction-keeper --model '../my-bidding-model.sh' [...]
```

### Communicating with _bidding models_

TODO





## Installation

This project uses *Python 3.6.2*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/makerdao/auction-keeper.git
cd auction-keeper
git submodule update --init --recursive
pip3 install -r requirements.txt
```

For some known macOS issues see the [pymaker](https://github.com/makerdao/pymaker) README.


## Usage

**TODO**


## License

See [COPYING](https://github.com/makerdao/auction-keeper/blob/master/COPYING) file.
