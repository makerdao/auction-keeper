# auction-keeper

[![Build Status](https://travis-ci.com/makerdao/auction-keeper.svg?branch=master)](https://travis-ci.com/makerdao/auction-keeper)
[![codecov](https://codecov.io/gh/makerdao/auction-keeper/branch/master/graph/badge.svg)](https://codecov.io/gh/makerdao/auction-keeper)

The _DAI Stablecoin System_ incentivizes external agents, called _keepers_, to automate certain operations around the
Ethereum blockchain.  The purpose of `auction-keeper` is to:
 * Seek out opportunities and start new auctions
 * Detect auctions started by other participants
 * Bid on auctions by converting token prices into bids

Check out the <a href="https://youtu.be/wevzK3ADEjo?t=733">July 23rd, 2019 community meeting</a>
for some more information about MCD auctions and the purpose of this component.

`auction-keeper` can participate in `flip` (collateral sale), `flap` (MKR buy-and-burn)
and `flop` (MKR minting) auctions. Its unique feature is the ability to plug in external
_bidding models_, which tell the keeper when and how high to bid. This keeper can be safely
left running in background. The moment it notices or starts a new auction it will spawn a new instance
of a _bidding model_ for it and then act according to its instructions. _Bidding models_ will
be automatically terminated by the keeper the moment the auction expires.  The keeper also
automatically `deal`s expired auctions if it's us who won them.

This keeper is intended to be a reference implementation.  It may be used as-is, or pieces borrowed to
develop your own auction trading bot.

<https://chat.makerdao.com/channel/keeper>


## Architecture

`auction-keeper` directly interacts with `Flipper`, `Flapper` and `Flopper` auction contracts
deployed to the Ethereum blockchain. Decisions which involve pricing are delegated to _bidding models_.

_Bidding models_ are simple processes, external to the main `auction-keeper` process. As they do not have to know
anything about blockchain and smart contracts, they can be implemented in basically any programming language.
The only thing they need to do is to read and write JSON documents they exchange with `auction-keeper`. The simplest
example of a bidding model is a shell script which echoes a fixed price.


### Monitoring ongoing auctions and discovering new ones

The main task of this keeper, as already outlined above, is to constantly monitor all ongoing auctions,
discover new ones, ensure that an instance of _bidding model_ is running for each auction, provide
these instances of the current status of their auctions and bid according to decisions taken by them.

The way the auction discovery and monitoring mechanism works at the moment is simplistic for illustration purposes.
It basically operates as a loop which kicks in on every new block enumerating all auctions from `1` to `kicks`.
Bidding models are checked periodically and submitted where appropriate.


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
* `gasPrice` (deprecated) - gas price in Wei to use when sending the bid.

A sample message sent from the model to the keeper may look like:
```json
{"price": "750.0"}
```

Whenever the keeper and the model communicate in terms of prices, it is the MKR/DAI price (for `flap`
and `flop` auctions) or the collateral price expressed in DAI e.g. DGX/DAI (for `flip` auctions).

Any messages writen by a _bidding model_ to **stderr** will be passed through by the keeper to its logs.
This is the most convenient way of implementing logging from _bidding models_.

**No facility is provided to prevent you from bidding an unprofitable price.**  Please ensure you understand how your
model produces prices and how prices are consumed by the keeper for each of the auction types in which you participate.

### Simplest possible _bidding model_

If you just want to bid a fixed price for each auction, this is the simplest possible _bidding model_
you can use:

```bash
#!/usr/bin/env bash

while true; do
  echo "{\"price\": \"723.0\"}" # put your desired price amount here
  sleep 120                      # locking the price for n seconds
done
```

The stdout provides a price for the collateral (for `flip` auctions) or MKR (for `flap` and `flop` auctions).  The
sleep locks the price in place for the specified duration, after which the keeper will restart the price model and read a new price.  
Consider this your price update interval.  To conserve system resources, take care not to set this too low.

### Other bidding models
Thanks to our community for these examples:
 * *banteg*'s [Python boilerplate model](https://gist.github.com/banteg/93808e6c0f1b9b6b470beaba5a140813)
 * *theogravity*'s [NodeJS bidding model](https://github.com/theogravity/dai-auction-keeper)


## Limitations

* If an auction started before the keeper was started, this keeper will not participate in it until the next block
is mined.
* This keeper does not explicitly handle global settlement, and may submit transactions which fail during shutdown.
* Some keeper functions incur gas fees regardless of whether a bid is submitted.  This includes, but is not limited to,
the following actions:
  * submitting approvals
  * adjusting the balance of surplus to debt
  * queuing debt for auction
  * biting a vault or starting a flap or flop auction
* The keeper does not check model prices until an auction exists.  When configured to create new auctions, it will
`bite`, `flap`, or `flop` in response to opportunities regardless of whether or not your Dai or MKR balance is
sufficient to participate.  This too imposes a gas fee.
* Biting vaults to kick off new collateral auctions is an expensive operation.  To do so without a VulcanizeDB
subscription, the keeper initializes a cache of urn state by scraping event logs from the chain.  The keeper will then
continuously refresh urn state to detect undercollateralized urns.
   * Despite batching log queries into multiple requests, Geth nodes are generally unable to initialize the urn state
   cache in a reasonable amount of time.  As such, Geth is not recommended for biting vaults.
   * To manage resources, it is recommended to run separate keepers using separate accounts to bite (`--kick-only`)
   and bid (`--bid-only`).


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

Run `bin/auction-keeper -h` without arguments to see an up-to-date list of arguments and usage information.

To participate in all auctions, a separate keeper must be configured for `flip` of each collateral type, as well as
one for `flap` and another for `flop`.  Collateral types (`ilk`s) combine the name of the token and a letter
corresponding to a set of risk parameters.  For example, `ETH-A` and `ETH-B` are two different collateral types for the
same underlying token (WETH).

Configure `--from-block` to the block where MCD was deployed.  One way to find this is to look at the `MCD_DAI`
contract of the deployment you are using and determine the block in which it was deployed.

![example list of keepers](README-keeper-config-example.png)

Please note **collateral types in the table above are provided for illustrative purposes, and should not be interpreted
as an endorsement of which collaterals should be deployed to mainnet**, which will be determined by an appropriate
governance process.  A complete list of `ilk`s for a deployment may be gleaned from the `addresses.json`.

## Gas price strategy

Auction keeper can use one of several sources for the initial gas price of a transaction:  
 * The `--oracle-gas-price` switch will use a gas price aggregated across multiple gas oracles.  Recommend passing 
 `--ethgasstation-api-key MY_API_KEY` and `--etherscan-api-key MY_API_KEY`, as both API keys are currently free.  
 * The `--fixed-gas-price` switch allows specifying a **fixed** initial price in Gwei (e.g. `--fixed-gas-price 33.3`).

If neither `--oracle-gas-price` nor `--fixed-gas-price` is configured, or if gas oracles are not producing prices, 
the keeper will choose a starting gas price determined by your node.  When not using `--fixed-gas-price`, 
`--gas-initial-multiplier` (default `1.0`, or 100%) allows you to configure a more aggressive initial gas price.

Auction keeper periodically attempts to increase gas price when transactions are queueing.  After a few blocks, a
transaction's gas price will be multiplied by `--gas-reactive-multiplier` (default `1.125`, an increase of 12.5%)
until it is mined or `--gas-maximum` (default 2000 Gwei) is reached.  
Note that [Parity](https://wiki.parity.io/Transactions-Queue#dropping-conditions), as of this writing, requires a
minimum gas increase of `1.125` to propagate transaction replacement; this should be treated as a minimum
value unless you want replacements to happen less frequently.

This gas strategy is used by keeper in all interactions with chain.  When sending a bid, this strategy is used only
when the model does not provide a gas price.  Unless your price model is aware of your transaction status, it is
generally advisable to allow the keeper to manage gas prices for bids, and _not_ supply a `gasPrice` in your model.


### Accounting
Key points:
- Dai must be **joined** from a token balance to the `Vat` for bidding on `flip` and `flop` auctions.
- Won collateral can be **exited** from the `Vat` to a token balance after a won auction is dealt (closed).
- MKR for/from `flap`/`flop` auctions is managed directly through token balances and is never joined to the `Vat`.

The keeper provides facilities for managing `Vat` balances, which may be turned off to manage manually.
To manually control the amount of Dai in the `Vat`, pass `--keep-dai-in-vat-on-exit` and `--keep-gem-in-vat-on-exit`,
set `--return-gem-interval 0`, and do not pass `--vat-dai-target`.

Warnings: **Do not use an `eth-from` account on multiple keepers** as it complicates Vat inventory management and
will likely cause nonce conflicts.  Using an `eth-from` account with an open vault is also discouraged.

#### Dai
All auction contracts exclusively interact with Dai (for all auctions) in the `Vat`.  `--vat-dai-target` may be set to
the amount you wish to maintain, or `all` to join your account's entire token balance.  Rebalances do not account for
Dai moved from the `Vat` to an auction contract for an active bid.  Dai is rebalanced per `--vat-dai-target` when:
- The keeper starts up
- `Vat` balance is insufficient to place a bid
- An auction is dealt

To avoid transaction spamming, small "dusty" Dai balances will be ignored (until the keeper exits, if so configured).  
By default, all Dai in your `eth-from` account is exited from the `Vat` and added to your token balance when the keeper
is terminated normally.  This feature may be disabled using `--keep-dai-in-vat-on-exit`.

#### Collateral (flip auctions)
Won collateral is periodically exited by setting `--return-gem-interval` to the number of seconds between balance
checks.  Collateral is exited from the `Vat` when the keeper is terminated normally unless `--keep-gem-in-vat-on-exit`
is specified.

#### Other tools
Alternatively, [mcd-cli](https://github.com/makerdao/mcd-cli) can be used to manually manage `Vat` balances.
Here is an example to join 6000 Dai on a testnet,
and exit 300 Dai on Kovan, respectively:
```bash
mcd -C testnet dai join 6000
mcd -C kovan dai exit 300
```
`mcd-cli` requires installation and configuration; view the
[mcd-cli README](https://github.com/makerdao/mcd-cli#mcd-command-line-interface) for more information.


### Managing resources

#### Minimize load on your node

To start `flip` auctions, the keeper needs a list of urns and the collateralization ratio of each urn.  There are
two ways to retrieve the list of urns:
 * **Set `--from-block` to the block where the first urn was created** to scrape the chain for `frob` events.  
    The application will spend significant time (>25 minutes for ETH-A) populating an initial list.  Afterward, events
    will be queried back to the last cached block to detect new urns.  The state of all urns will be queried
    continuously (>6 minutes for ETH-A).  The following table suggests `--from-block` values based on when the `join`
    contract was deployed for some collateral types and chains.
    
    | Ilk    | Mainnet  | Kovan    |
    | :------| :--------| :--------|
    | ETH-A  | 8928176  | 14764566 |
    | ETH-B  | 11049708 | 21497286 |
    | BAT-A  | 8928185  | 14764576 |
    | WBTC-A | 9975676  | 18270296 |
    | ZRX-A  | 10323394 | 19243343 |
    | KNC-A  | 10323392 | 19243288 |
    | MANA-A | 10510886 | 19731368 |
    | USDT-A | 10790625 | 20611963 |
    | COMP-A | 10967218 | 20805417 |
    | LRC-A  | 10950762 | 20149845 |
    | LINK-A | 10950763 | 20957887 |
    | BAL-A  | 11198616 | 21647334 |
    | YFI-A  | 11198626 | 21678352 |
    | UNI-A  | 11420948 | 22432437 |
    | RENBTC-A | 11420957 | 22406388 |
    | AAVE-A   | 11471509 | 22609978 |
    | UNIV2DAIETH-A  | 11477786 | 22636280 |
    | UNIV2WBTCETH-A | 11700394 | n/a |
    | UNIV2USDCETH-A | 11700453 | n/a |
    | UNIV2DAIUSDC-A | 11791208 | n/a |
    | UNIV2ETHUSDT-A | 11791262 | n/a |
    | UNIV2WBTCDAI-A | 11882262 | n/a |
    | UNIV2AAVEETH-A | 11882246 | n/a |

 * **Subscribe to TokenFlow** market data, which is currently in beta.  Visit https://api.mcdstate.info/ for more 
    information.

 * **Deploy a [VulcanizeDB instance](https://github.com/makerdao/vdb-mcd-transformers) to maintain your own
    copy of urn state** in PostgresQL, and then set `--vulcanize-endpoint` to your instance.  If you're using a hosted 
   Vulcanize endpoint, you can provide an API key for basic authentication with the `--vulcanize-key` argument.

To start `flop` auctions, the keeper needs a list of bites to queue debt.  To manage performance, periodically
adjust `--from-block` to the block where the first bite which has not been `flog`ged.

The `--min-auction` argument arbitrarily ignores older completed auctions, such that the keeper needn't check their
status.  The `--max-auctions` argument allows you to limit the number of bidding models created to handle active
auctions.  Both switches help reduce the number of _requests_ (not just transactions) made to the node.

#### Transaction management

Bid management can be sharded across multiple keepers by **auction id**.  To do this, configure `--shards` with the
number of keepers you will run, and a separate `--shard-id` for each keeper, counting from 0.  For example, to
configure three keepers, set `--shards 3` and assign `--shard-id 0`, `--shard-id 1`, `--shard-id 2` for the three
keepers.  **Kicks are not sharded**; for an auction contract, only one keeper should be configured to `kick`.

If you are sharding across multiple accounts, you may wish to have another account handle all your `deal`s.  The
`--deal-for` argument allows you to specify a space-delimited list of accounts for which you'll deal auctions.  You
may disable dealing auctions by specifying `--deal-for NONE` in each of your shards.  If you'd like to donate your gas
to deal auctions for all participants, `--deal-for ALL` is also supported.  Unlike kicks, **deals are sharded**, so
remove sharding configuration if running a dedicated deal keeper.

Too many pending transactions can fill up the transaction queue, causing a subsequent transaction to be dropped.  By
waiting a small `--bid-delay` after each bid, multiple transactions can be submitted asynchronously while still
allowing some time for older transactions to complete, freeing up the queue.  Many parameters determine the appropriate
amount of time to wait.  For illustration purposes, assume the queue can hold 12 transactions, and gas prices are
reasonable.  In this environment, a bid delay of 1.2 seconds might provide ample time for transactions at the front of
the queue to complete.  [Etherscan.io](etherscan.io) can be used to view your account's pending transaction queue.

Upon startup, the keeper will clear its transaction queue.  This helps recover from insufficiently-aggressive gas
configuration and reduces gas-wasting transactions.

#### Hardware and operating system resources

 * The most expensive keepers are `flip` and `flop` keepers configured to `kick` new auctions.
 * To prevent process churn, ensure your pricing model stays running for a reasonable amount of time.


## Infrastructure

This keeper connects to the Ethereum network using [Web3.py](https://github.com/ethereum/web3.py) and interacts with
the Dai Stablecoin System (DSS) using [pymaker](https://github.com/makerdao/pymaker).  A connection to an Ethereum node
(`--rpc-host`) is required.  [Parity](https://www.parity.io/ethereum/) and [Geth](https://geth.ethereum.org/) nodes are
supported over HTTP.  Web3.py's `WebsocketProvider` [does not support](https://github.com/ethereum/web3.py/issues/1413) 
multiple threads awaiting a response from the websocket.  A _full_ or _archive_ node is required; _light_ nodes are not 
supported.

If you don't wish to run your own Ethereum node, third-party providers are available.  This software has been tested
with [ChainSafe](https://chainsafe.io/) and [QuikNode](https://v2.quiknode.io/).  When using 
[Infura](https://infura.io/) and kicking off flip auctions, reduce `--chunk-size` to 1/10th of the default.

## Testing

This project uses [pytest](https://docs.pytest.org/en/latest/) for unit testing.  Testing depends upon on a Dockerized
local testchain included in `lib\pymaker\tests\config`.

In order to be able to run tests, please install development dependencies first by executing:
```
pip3 install -r requirements-dev.txt
```

You can then run all tests with:
```
./test.sh
```


## License

See [COPYING](https://github.com/makerdao/auction-keeper/blob/master/COPYING) file.

### Disclaimer

YOU (MEANING ANY INDIVIDUAL OR ENTITY ACCESSING, USING OR BOTH THE SOFTWARE INCLUDED IN THIS GITHUB REPOSITORY) EXPRESSLY UNDERSTAND AND AGREE THAT YOUR USE OF THE SOFTWARE IS AT YOUR SOLE RISK.
THE SOFTWARE IN THIS GITHUB REPOSITORY IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
YOU RELEASE AUTHORS OR COPYRIGHT HOLDERS FROM ALL LIABILITY FOR YOU HAVING ACQUIRED OR NOT ACQUIRED CONTENT IN THIS GITHUB REPOSITORY. THE AUTHORS OR COPYRIGHT HOLDERS MAKE NO REPRESENTATIONS CONCERNING ANY CONTENT CONTAINED IN OR ACCESSED THROUGH THE SERVICE, AND THE AUTHORS OR COPYRIGHT HOLDERS WILL NOT BE RESPONSIBLE OR LIABLE FOR THE ACCURACY, COPYRIGHT COMPLIANCE, LEGALITY OR DECENCY OF MATERIAL CONTAINED IN OR ACCESSED THROUGH THIS GITHUB REPOSITORY.
