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


## Overall architecture

`auction-keeper` is responsible for directly interacting with `Flipper`, `Flapper` and `Flopper` auction contracts
deployed to the Ethereum blockchain. It it responsible for querying and monitoring the current auction
state, and also for sending all Ethereum transactions. At the same time all all decision making
is delegated to _bidding models_.

_Bidding models_ are simple processes, external to the main `auction-keeper` process. As they do not have to know
anything about blockchain and smart contracts, they can be implemented in basically any programming language.
The only thing they need to do is to read and write JSON documents they exchange with `auction-keeper`.


### Monitoring ongoing auctions and discovering new ones

The main task of this keeper, as already outlined above, is to constantly monitor all ongoing auctions,
discover new ones, ensure that an instance of _bidding model_ is running for each auction, provide
these instances of the current status of their auctions and bid according to decisions taken by them.

The way the auction discovery and monitoring mechanism works at the moment is pretty lame. It basically
operates as a loop which kicks in on every new block and simply enumerates all auctions from `1` to `kicks`.
Even if the _bidding model_ decides to send a bid, it will not be processed by the keeper until the next
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

`auction-keeper` communicates with _bidding models_ via their standard input and standard output.

Straight away after the process gets started, and every time the auction state changes, the keeper
sends a one-line JSON document to the **standard input** of the _bidding model_ process.
Sample message sent from the keeper to the model looks like:
```json
{"id": "6", "flapper": "0xf0afc3108bb8f196cf8d076c8c4877a4c53d4e7c", "bid": "7.142857142857142857", "lot": "10000.000000000000000000", "beg": "1.050000000000000000", "guy": "0x00531a10c4fbd906313768d277585292aa7c923a", "era": 1530530620, "tic": 1530541420, "end": 1531135256, "price": "1400.000000000000000028"}
```

The meaning of individual fields:
* `id` - auction identifier.
* `flipper` - Ethereum address of the `Flipper` contract (only for `flip` auctions).
* `flapper` - Ethereum address of the `Flapper` contract (only for `flap` auctions).
* `flopper` - Ethereum address of the `Flopper` contract (only for `flop` auctions).
* `bid` - current highest bid (will go up for `flip` and `flap` auctions).
* `lot` - amount being currently auctioned (will go down for `flip` and `flop` auctions).
* `tab` - bid value which will cause the auction to enter the `dent` phase (only for `flip` auctions).
* `beg` - minimum price increment (`1.05` means minimum 5% price increment).
* `guy` - Ethereum address of the current highest bidder.
* `era` - current time (in seconds since the UNIX epoch).
* `tic` - time when the current bid will expire (`null` if no bids yet).
* `end` - time when the entire auction will expire.
* `price` - current price being tendered (can be `null` if price is infinity).

_Bidding models_ should never make an assumption that messages will be sent only when auction state changes.
It is perfectly fine for the `auction-keeper` to periodically send the same messages to _bidding models_.

At the same time, the `auction-keeper` reads one-line messages from the **standard output** of the _bidding model_
process and tries to parse them as JSON documents. Then it extracts two fields from that document:
* `price` - the maximum (for `flip` and `flop` auctions) or the minimum (for `flap` auctions) price
  the model is willing to bid.
* `gasPrice` (optional) - gas price in Wei to use when sending the bid.

Sample message send from the model to the keeper may look like:
```json
{"price": "750.0", "gasPrice": 7000000000}
```

Whenever the keeper and the model communicate in terms of prices, it is the MKR/DAI price (for `flap`
and `flop` auctions) or the collateral price expressed in DAI e.g. DGX/DAI (for `flip` auctions).

Any messages writen by a _bidding model_ to **stderr** will be passed through by the keeper to its logs.
This is the most convenient way of implementing logging from _bidding models_.


### Simplest possible _bidding model_

If you just want to bid a fixed price for each auction, this is the simplest possible _bidding model_
you can use:

```bash
#!/usr/bin/env bash

echo "{\"price\": \"750.0\"}"  # put your price here
sleep 1000000
```


## Installation

This project uses *Python 3.6.6*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/makerdao/auction-keeper.git
cd auction-keeper
git submodule update --init --recursive
pip3 install -r requirements.txt
```

For some known Ubuntu and macOS issues see the [pymaker](https://github.com/makerdao/pymaker) README.


## Usage

```
usage: auction-keeper [-h] [--rpc-host RPC_HOST] [--rpc-port RPC_PORT]
                      [--rpc-timeout RPC_TIMEOUT] --eth-from ETH_FROM
                      (--flipper FLIPPER | --flapper FLAPPER | --flopper FLOPPER)
                      --model MODEL [--debug]

optional arguments:
  -h, --help            show this help message and exit
  --rpc-host RPC_HOST   JSON-RPC host (default: `localhost')
  --rpc-port RPC_PORT   JSON-RPC port (default: `8545')
  --rpc-timeout RPC_TIMEOUT
                        JSON-RPC timeout (in seconds, default: 10)
  --eth-from ETH_FROM   Ethereum account from which to send transactions
  --flipper FLIPPER     Ethereum address of the Flipper contract
  --flapper FLAPPER     Ethereum address of the Flapper contract
  --flopper FLOPPER     Ethereum address of the Flopper contract
  --model MODEL         Commandline to use in order to start the bidding model
  --debug               Enable debug output
```


## License

See [COPYING](https://github.com/makerdao/auction-keeper/blob/master/COPYING) file.

### Disclaimer

YOU (MEANING ANY INDIVIDUAL OR ENTITY ACCESSING, USING OR BOTH THE SOFTWARE INCLUDED IN THIS GITHUB REPOSITORY) EXPRESSLY UNDERSTAND AND AGREE THAT YOUR USE OF THE SOFTWARE IS AT YOUR SOLE RISK.
THE SOFTWARE IN THIS GITHUB REPOSITORY IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
YOU RELEASE AUTHORS OR COPYRIGHT HOLDERS FROM ALL LIABILITY FOR YOU HAVING ACQUIRED OR NOT ACQUIRED CONTENT IN THIS GITHUB REPOSITORY. THE AUTHORS OR COPYRIGHT HOLDERS MAKE NO REPRESENTATIONS CONCERNING ANY CONTENT CONTAINED IN OR ACCESSED THROUGH THE SERVICE, AND THE AUTHORS OR COPYRIGHT HOLDERS WILL NOT BE RESPONSIBLE OR LIABLE FOR THE ACCURACY, COPYRIGHT COMPLIANCE, LEGALITY OR DECENCY OF MATERIAL CONTAINED IN OR ACCESSED THROUGH THIS GITHUB REPOSITORY. 
