# auction-keeper

[![Build Status](https://travis-ci.org/reflexer-labs/auction-keeper.svg?branch=master)](https://travis-ci.org/reflexer-labs/auction-keeper)
[![codecov](https://codecov.io/gh/reflexer-labs/auction-keeper/branch/master/graph/badge.svg)](https://codecov.io/gh/reflexer-labs/auction-keeper)

The purpose of `auction-keeper` is to:
 * Seek out opportunities and start new auctions
 * Detect auctions started by other participants
 * Bid on auctions by converting token prices into bids

`auction-keeper` can participate in collateral, surplus and debt auctions. Its unique feature is the ability to plug in external
_bidding models_, which tell the keeper when and how high to bid. This keeper can be safely left running in background. The moment it notices or starts a new auction it will spawn a new instance of a _bidding model_ for it and then act according to its instructions. _Bidding models_ will
be automatically terminated by the keeper the moment the auction expires.  The keeper also automatically settles expired auctions if it's us who won them.

This keeper is intended to be a reference implementation.  It may be used as-is, or pieces borrowed to
develop your own auction trading bot.

<https://discord.gg/kB4vcYs>

## Architecture

`auction-keeper` directly interacts with auction contracts deployed to the Ethereum blockchain. Decisions which involve pricing are delegated to _bidding models_.

_Bidding models_ are simple processes, external to the main `auction-keeper` process. As they do not have to know
anything about blockchain and smart contracts, they can be implemented in basically any programming language.
The only thing they need to do is to read and write JSON documents they exchange with `auction-keeper`. The simplest
example of a bidding model is a shell script which echoes a fixed price.

### Monitoring ongoing auctions and discovering new ones

The main task of this keeper, as already outlined above, is to constantly monitor all ongoing auctions,
discover new ones, ensure that an instance of bidding model is running for each auction, provide
these instances of the current status of their auctions and bid according to decisions taken by them.

The way the auction discovery and monitoring mechanism works at the moment is simplistic for illustration purposes.
It basically operates as a loop which kicks in on every new block enumerating all auctions from `1` to `auctionsStarted`.
Bidding models are checked every 2 seconds and submitted where appropriate.

### Starting and stopping bidding models

`auction-keeper` maintains a collection of child processes, as each bidding model is its own dedicated
process. New processes (new _bidding model_ instances) are spawned by executing a command according to the
`--model` commandline parameter. These processes are automatically terminated (via `SIGKILL`) by the keeper
shortly after their associated auction expires.

Whenever the _bidding model_ process dies, it gets automatically respawned by the keeper.

Example:
```bash
bin/auction-keeper --model '../my-bidding-model.sh' [...]
```

### Communicating with bidding models

`auction-keeper` communicates with bidding models via their standard input and standard output.

Straight away after the process gets started, and every time the auction state changes, the keeper
sends a one-line JSON document to the **standard input** of the bidding model process.
Sample message sent from the keeper to the model looks like:
```json
{"id": "6", "surplusAuctionHouse": "0xf0afc3108bb8f196cf8d076c8c4877a4c53d4e7c", "bidAmount": "7.142857142857142857", "amountToSell": "10000.000000000000000000", "bidIncrease": "1.050000000000000000", "highBidder": "0x00531a10c4fbd906313768d277585292aa7c923a", "era": 1530530620, "bidExpiry": 1530541420, "auctionDeadline": 1531135256, "price": "1400.000000000000000028"}
```
## Keeper message for English Auction

The meaning of individual fields:
* `id` - auction identifier.
* `bidAmount` - current highest bid (will go up for collateral and surplus auctions).
* `amountToSell` - amount being currently auctioned (will go down for surplus and debt auctions).
* `amountToRaise` - bid value which will cause the auction to enter its second phase (only for collateral auctions).
* `bidIncrease` - minimum price increment (`1.05` means minimum 5% price increment).
* `highBidder` - Ethereum address of the current highest bidder.
* `era` - current time (in seconds since the UNIX epoch).
* `bidExpiry` - time when the current bid will expire (`null` if no bids yet).
* `auctionDeadline` - time when the entire auction will expire.
* `price` - current price being bid (can be `null` if price is infinity).

## Keeper message for Fixed Discount Auction

The meaning of individual fields:
* `id` - auction identifier.
* `amountToSell` - amount being currently auctioned (will go down for surplus and debt auctions).
* `amountToRaise` - bid value which will cause the auction to enter its second phase (only for collateral auctions).
* `soldAmount` - total collateral sold for this auction
* `raisedAmount` - total system count raised from this auction
* `block_time` - current time (in seconds since the UNIX epoch).
* `auctionDeadline` - time when the entire auction will expire.

Bidding models should never make an assumption that messages will be sent only when auction state changes.
It is perfectly fine for the `auction-keeper` to periodically send the same messages to bidding models.

At the same time, the `auction-keeper` reads one-line messages from the **standard output** of the bidding model
process and tries to parse them as JSON documents. Then it extracts two fields from that document:
* `price` - the maximum (for collateral and debt auctions) or the minimum (for surplus auctions) price
  the model is willing to bid. This value is ignored for fixed discount collateral auctions
* `gasPrice` (optional) - gas price in Wei to use when sending the bid.

## Sample model output for English Auction 
A sample message sent from the model to the keeper may look like:
```json
{"price": "750.0", "gasPrice": 7000000000}
```
### Sample model output for Fixed Discount Auction 
NOTE: Collateral price is determined by the fixed discount percentage, so only `gas` is supported for fixed discount
      collateral auctions.
A sample message sent from the model to the keeper may look like:
```json
{"gasPrice": 7000000000}
```

Whenever the keeper and the model communicate in terms of prices, it is the PROT/SYS_COIN price (for surplus
and debt auctions) or the collateral price expressed in system coins e.g. ETH/SYS_COIN (for surplus auctions).

Any messages writen by a _bidding model_ to **stderr** will be passed through by the keeper to its logs.
This is the most convenient way of implementing logging from _bidding models_.

**No facility is provided to prevent you from bidding an unprofitable price.**  Please ensure you understand how your
model produces prices and how prices are consumed by the keeper for each of the auction types in which you participate.

### Simplest possible English Auction bidding model

If you just want to bid a fixed price for each auction, this is the simplest possible _bidding model_
you can use:

```bash
#!/usr/bin/env bash

while true; do
  echo "{\"price\": \"723.0\"}"  # put your desired price amount here
  sleep 120                      # locking the price for n seconds
done
```

### Simplest possible Fixed Discount bidding model


```bash
#!/usr/bin/env bash
while true; do
  echo "{}"
  sleep 120                   
done
```
Gas price is optional for fixed discount models. If you want to start with a fixed gas price, you can add it.

```bash
#!/usr/bin/env bash

while true; do
  echo "{\"gas\": \"60\"}"    # put your desired gas price in GWEI here
  sleep 120                   # locking the gas price for n seconds
done
```

The stdout provides a price for the collateral (for collateral auctions) or protocol tokens (for surplus and debt auctions). The
sleep locks the price in place for the specified duration, after which the keeper will restart the price model and read a new price.  
Consider this your price update interval. To conserve system resources, take care not to set this too low.

### Other bidding models
Thanks to our community for these examples:
 * *banteg*'s [Python boilerplate model](https://gist.github.com/banteg/93808e6c0f1b9b6b470beaba5a140813)

## Limitations

* If an auction started before the keeper was started, this keeper will not participate in it until the next block
is mined.
* This keeper does not explicitly handle global settlement, and may submit transactions which fail during shutdown.
* Some keeper functions incur gas fees regardless of whether a bid is submitted.  This includes, but is not limited to,
the following actions:
  * submitting approvals
  * adjusting the balance of surplus to debt
  * queuing debt for auction
  * liquidating a SAFE or starting a surplus or debt auction
* The keeper does not check model prices until an auction exists.  When configured to create new auctions, it will
`liquidateSAFE`, start a new surplus or debt auction in response to opportunities regardless of whether or not your system coin or protocol token balance is sufficient to participate.  This too imposes a gas fee.
* Liquidating SAFEs to start new collateral auctions is an expensive operation.  To do so without a subgraph
subscription, the keeper initializes a cache of safe state by scraping event logs from the chain.  The keeper will then
continuously refresh safe state to detect undercollateralized SAFEs.
   * Despite batching log queries into multiple requests, Geth nodes are generally unable to initialize the safe state
   cache in a reasonable amount of time.  As such, Geth is not recommended for liquidating SAFEs.
   * To manage resources, it is recommended to run separate keepers using separate accounts to bite (`--start-auctions-only`)
   and bid (`--bid-only`).

## Installation

This project uses *Python 3.6.6*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/reflexer-labs/auction-keeper.git
cd auction-keeper
git submodule update --init --recursive
pip3 install -r requirements.txt
```

For some known Ubuntu and macOS issues see the [pyflex](https://github.com/reflexer-labs/pyflex) README.

## Usage

Run `bin/auction-keeper -h` without arguments to see an up-to-date list of arguments and usage information.

To participate in all auctions, a separate keeper must be configured for collateral of each collateral type, as well as
one for surplus and another one for debt auctions.  Collateral types combine the name of the token and a letter
corresponding to a set of risk parameters.  For example, `ETH-A` and `ETH-B` are two different collateral types for the
same underlying token (WETH).

Configure `--from-block` to the block where GEB was deployed.  One way to find this is to look at the `STARTING_BLOCK_NUMBER`
of the deployment you are using.

Please note **collateral types in the table above are provided for illustrative purposes, and should not be interpreted
as an endorsement of which collaterals should be deployed to mainnet**, which will be determined by an appropriate
governance process.  A complete list of collateral types for a deployment may be gleaned from the `addresses.json`.

## Gas price strategy

Auction keeper can use one of several sources for the initial gas price of a transaction:  
 * **Ethgasstation** if a key is passed as `--ethgasstation-api-key` (e.g. `--ethgasstation-api-key MY_API_KEY`)  
 * **Etherchain.org** if keeper started with `--etherchain-gas-price` switch  
 * **POANetwork** if keeper started with `--poanetwork-gas-price` switch. An alternate URL can be passed as `--poanetwork-url`,
    that is useful when server hosted locally (e.g. `--poanetwork-url http://localhost:8000`)  
 * The `--fixed-gas-price` switch allows specifying a **fixed** initial price in Gwei (e.g. `--fixed-gas-price 12.4`)

When using an API source for initial gas price, `--gas-initial-multiplier` (default `1.0`, or 100%) tunes the initial
value provided by the API.  This is ignored when using `--fixed-gas-price` and when no strategy is chosen.  If no
initial gas source is configured, or the gas price API produces no result, then the keeper will start with a price
determined by your node.

Auction keeper periodically attempts to increase gas price when transactions are queueing.  Every 30 seconds, a
transaction's gas price will be multiplied by `--gas-reactive-multiplier` (default `1.125`, an increase of 12.5%)
until it is mined or `--gas-maximum` (default 2000 Gwei) is reached.  
Note that [Parity](https://wiki.parity.io/Transactions-Queue#dropping-conditions), as of this writing, requires a
minimum gas increase of `1.125` to propagate transaction replacement; this should be treated as a minimum
value unless you want replacements to happen less frequently than 30 seconds (2+ blocks).

This gas strategy is used by keeper in all interactions with chain.  When sending a bid, this strategy is used only
when the model does not provide a gas price.  Unless your price model is aware of your transaction status, it is
generally advisable to allow the keeper to manage gas prices for bids, and not supply a `gasPrice` in your model.

### Accounting
Key points:
- System coins must be **joined** from a token balance to the `SAFEEngine` for bidding on collateral and debt auctions.
- Won collateral can be **exited** from the `SAFEEngine` to a token balance after a won auction is settled.
- Protocol tokens for/from surplus/debt auctions is managed directly through token balances and is never joined to the `SAFEEngine`.

The keeper provides facilities for managing `SAFEEngine` balances, which may be turned off to manage manually.
To manually control the amount of system coins in the `SAFEEngine`, pass `--keep-system-coin-in-safe-engine-on-exit` and `--keep-collateral-in-safe-engine-on-exit`,
set `--return-collateral-interval 0`, and do not pass `--safe-engine-system-coin-target`.

Warnings: **Do not use an `eth-from` account on multiple keepers** as it complicates SAFEEngine inventory management and
will likely cause nonce conflicts.  Using an `eth-from` account with an open SAFE is also discouraged.

#### System Coins
All auction contracts exclusively interact with system coins (for all auctions) in the `SAFEEngine`. `--safe-engine-system-coin-target` may be set to
the amount you wish to maintain, or `all` to join your account's entire token balance.  Rebalances do not account for
system coins moved from the `SAFEEngine` to an auction contract for an active bid.  system coins is rebalanced per `--safe-engine-system-coin-target` when:
- The keeper starts up
- `SAFEEngine` balance is insufficient to place a bid
- An auction is settled

To avoid transaction spamming, small "dusty" system coins balances will be ignored (until the keeper exits, if so configured).  
By default, all system coins in your `eth-from` account is exited from the `SAFEEngine` and added to your token balance when the keeper
is terminated normally.  This feature may be disabled using `--keep-system-coin-in-safe-engine-on-exit`.

#### Collateral Auctions
Won collateral is periodically exited by setting `--return-collateral-interval` to the number of seconds between balance
checks.  Collateral is exited from the `SAFEEngine` when the keeper is terminated normally unless `--keep-collateral-in-safe-engine-on-exit`
is specified.

### Managing resources

#### Minimize load on your node

To start collateral auctions, the keeper needs a list of SAFEs and the collateralization ratio of each safe.  There are
two ways to retrieve the list of SAFEs:
 * **Set `--from-block` to the block where the first safe was created** to scrape the chain for `ModifySAFECollateralization` events.  
    The application will spend significant time (>25 minutes for ETH-A) populating an initial list.  Afterward, events
    will be queried back to the last cached block to detect new SAFEs.  The state of all SAFEs will be queried
    continuously (>6 minutes for ETH-A).  The following table suggests `--from-block` values based on when the `join`
    contract was deployed for some collateral types and chains.

 * **Connect to a subgraph indexing the specific GEB you are targetting by setting `--subgraph-endpoint`.  This will conserve
    resources on your node and keeper and reduces check time for SAFEs.

To start debt auctions, the keeper needs a list of liquidation events to queue debt.  To manage performance, periodically
adjust `--from-block` to the block where the first liquidation which has not been `popDebtFromQueue`.

The `--min-auction` argument arbitrarily ignores older completed auctions, such that the keeper needn't check their
status.  The `--max-auctions` argument allows you to limit the number of bidding models created to handle active
auctions.  Both switches help reduce the number of _requests_ (not just transactions) made to the node.

#### Transaction management

Bid management can be sharded across multiple keepers by **auction id**.  To do this, configure `--shards` with the
number of keepers you will run, and a separate `--shard-id` for each keeper, counting from 0.  For example, to
configure three keepers, set `--shards 3` and assign `--shard-id 0`, `--shard-id 1`, `--shard-id 2` for the three
keepers.  **Auction starts are not sharded**; for an auction contract, only one keeper should be configured to `startAuction`.

If you are sharding across multiple accounts, you may wish to have another account handle all your `settleAuction`s.  The
`--settle-for` argument allows you to specify a space-delimited list of accounts for which you'll settle auctions.  You
may disable settling auctions by specifying `--settle-for NONE` in each of your shards.  If you'd like to donate your gas
to settle auctions for all participants, `--settle-for ALL` is also supported.  Unlike auction starts, **settlements are sharded**, so
remove sharding configuration if running a dedicated deal keeper.

Too many pending transactions can fill up the transaction queue, causing a subsequent transaction to be dropped.  By
waiting a small `--bid-delay` after each bid, multiple transactions can be submitted asynchronously while still
allowing some time for older transactions to complete, freeing up the queue.  Many parameters determine the appropriate
amount of time to wait.  For illustration purposes, assume the queue can hold 12 transactions, and gas prices are
reasonable.  In this environment, a bid delay of 1.2 seconds might provide ample time for transactions at the front of
the queue to complete.  [Etherscan.io](etherscan.io) can be used to view your account's pending transaction queue.

#### Hardware and operating system resources

 * The most expensive keepers are collateral and debt keepers configured to start new auctions.
 * To prevent process churn, ensure your pricing model stays running for a reasonable amount of time.

## Infrastructure

This keeper connects to the Ethereum network using [Web3.py](https://github.com/ethereum/web3.py) and interacts with
the GEB using [pyflex](https://github.com/reflexer-labs/pyflex).  A connection to an Ethereum node
(`--rpc-host`) is required.  [Parity](https://www.parity.io/ethereum/) and [Geth](https://geth.ethereum.org/) nodes are
supported over HTTP. Websocket endpoints are not supported by `pyflex`.  A _full_ or _archive_ node is required;
_light_ nodes are not supported.

If you don't wish to run your own Ethereum node, third-party providers are available.  This software has been tested
with [ChainSafe](https://chainsafe.io/) and [QuikNode](https://v2.quiknode.io/). Infura is incompatible, however, because
it does not support the `eth_sendTransaction` RPC method which is used in pyflex.

## Testing

This project uses [pytest](https://docs.pytest.org/en/latest/) for unit testing.  Testing depends upon on a Dockerized
local testchain included in `lib\pyflex\tests\config`.

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
