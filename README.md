# auction-keeper

[![Build Status](https://travis-ci.org/makerdao/auction-keeper.svg?branch=master)](https://travis-ci.org/makerdao/auction-keeper)
[![codecov](https://codecov.io/gh/makerdao/auction-keeper/branch/master/graph/badge.svg)](https://codecov.io/gh/makerdao/auction-keeper)

The _DAI Stablecoin System_ incentivizes external agents, called _keepers_,
to automate certain operations around the Ethereum blockchain.

`auction-keeper` can participate in `flip` (collateral sale), `flap` (MKR buy-and-burn)
and `flop` (MKR minting) auctions. Its unique feature is the ability to plug in external
_bidding models_, which tell the keeper when and how high to bid. This keeper can be safely
left running in background. The moment it notices a new auction it will spawn a new instance
of a _bidding model_ for it and then act according to its instructions. The keeper will also
automatically `deal` expired auctions afterwards if it's us who won them.

Bear in mind that this keeper is still **early work in progress**. Many of the things described
here may still change.

<https://chat.makerdao.com/channel/keeper>


## Description

**TODO**



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
