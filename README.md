# auction-keeper

[![Build Status](https://travis-ci.org/reflexer-labs/auction-keeper.svg?branch=master)](https://travis-ci.org/reflexer-labs/auction-keeper)
[![codecov](https://codecov.io/gh/reflexer-labs/auction-keeper/branch/master/graph/badge.svg)](https://codecov.io/gh/reflexer-labs/auction-keeper)

The purpose of `auction-keeper` is to:
 * Start new auctions
 * Detect currently ongoing auctions
 * Bid on auctions

`auction-keeper` can participate in collateral, surplus and debt auctions. It can read an auction's status from an Ethereum or a [Graph](https://thegraph.com/) node. Its unique feature is the ability to plug in external _bidding models_ which tell the keeper when and how much to bid.

The keeper can be safely left running in background. The moment it notices or starts a new auction it will spawn a new instance of a _bidding model_ for it and then act according to its instructions. _Bidding models_ will be automatically terminated by the keeper the moment the auction expires.  The keeper can also settle expired auctions.

## Quickstart for Fixed Discount Collateral Auctions

### 1) Send RAI (aka system coins) to your keeper address

Buy RAI from [Uniswap v2](https://info.uniswap.org/pair/0xEBdE9F61e34B7aC5aAE5A4170E964eA85988008C) or open a SAFE and generate some RAI.

### 2) Run collateral auction-keeper

Modify `run_auction_keeper.sh` with your `ETH_RPC_URL`, `KEEPER_ADDRESS`, `KEYSTORE_DIR` and `KEYSTORE_FILE` values.
Then, `./run_auction_keeper.sh`

This will start a collateral `auction-keeper` for collateral type `ETH-A`. The keeper will use the Ethereum node at
`--rpc-host` and use the `--eth-from` Ethereum account, from keystore `--eth-key`.  The keystore password will be required upon startup.
`ALL` system coins owned by `--eth-from` will be `join`ed and available for bidding on fixed discount auctions. By default, collateral won in auctions will be `exit`ed to your account upon keeper exit.

#### Sample `run_auction_keeper.sh`
```
docker run -it \
        -v /my_keystore_dir:/keystore \
        reflexer/auction-keeper \
        --type collateral \
        --rpc-uri http://localhost:8545 \
        --eth-from 0xEA674fdDe714fd979de3EdF0F56AA9716B898ec8 \
        --eth-key "key_file=/keystore/my_key.json" \
        --safe-engine-system-coin-target ALL \
        --graph-endpoints https://api.thegraph.com/subgraphs/name/reflexer-labs/prai-mainnet,https://subgraph.reflexer.finance/subgraphs/name/reflexer-
labs/rai
```
**NOTE**: If using the Infura free-tier and you wish to stay under the 100k requests/day quota, add `--block-check-interval 10` and `--bid-check-interval 60` to `run_auction_keeper.sh`. However, this will make your keeper slower in responding to collateral auctions.

## Architecture

`auction-keeper` directly interacts with auction contracts deployed to the Ethereum blockchain. Bid prices are received from separate _bidding models_.

_Bidding models_ are simple processes that can be implemented in any programming language. They only need to pass JSON objects to and from `auction-keeper`. The simplest example of a bidding model is a shell script which echoes a fixed price.

## Responsibilities

The keeper is responsible with:

1) Monitoring all active auctions
2) Discovering new auctions
3) Ensuring a bidding model is running for each active auction
4) Passing auction status to each bidding model
5) Processing each bidding model output and submitting bids

### Monitoring active auctions and discovering new auctions

For every new block, all auctions from `1` to `auctionsStarted` are checked for active status.
If a new auction is detected, a new bidding model is started.

### Ensure bidding model is running for each active auction

`auction-keeper` maintains a collection of child processes, as each bidding model is its own dedicated process. New processes (new _bidding model_ instances) are spawned by executing the command passed to `--model`. These processes are automatically terminated (via `SIGKILL`) by the keeper shortly after their associated auction expires.

Whenever the _bidding model_ process dies, it gets automatically respawned by the keeper.

Example:
```bash
bin/auction-keeper --model '../my-bidding-model.sh' [...]
```

### Pass auction status to each bidding model

`auction-keeper` communicates with bidding models via their standard input and standard output.
When the auction state changes, the keeper sends a one-line JSON document to the **standard input** of the bidding model process.

Sample message sent from the keeper to the model looks like:
```json
{"id": "6", "surplus_auction_house": "0xf0afc3108bb8f196cf8d076c8c4877a4c53d4e7c", "bid_amount": "7.142857142857142857", "amount_to_sell": "10000.000000000000000000", "bid_increase": "1.050000000000000000", "high_bidder": "0x00531a10c4fbd906313768d277585292aa7c923a", "era": 1530530620, "bid_expiry": 1530541420, "auction_deadline": 1531135256, "price": "1400.000000000000000028"}
```

#### Fixed discount auction status passed to bidding model

The meaning of individual fields:
* `id` - auction identifier.
* `collateral_auction_house` - address of Fixed Discount Collateral Auction House
* `amount_to_sell` - amount being currently auctioned
* `amount_to_raise` - bid value which will cause the auction to settle
* `sold_amount` - total collateral sold for this auction
* `raised_amount` - total system coin raised from this auction
* `block_time` - current time (in seconds since the UNIX epoch).
* `auction_deadline` - time when the entire auction will expire.

Bidding models should never make an assumption that messages will be sent only when auction state changes.

At the same time, the `auction-keeper` reads one-line messages from the **standard output** of the bidding model
process and tries to parse them as JSON documents. Then it extracts two fields from that document:
* `price` - the maximum (for debt auctions) or the minimum (for surplus auctions) price
  the model is willing to bid. This value is ignored for fixed discount collateral auctions
* `gasPrice` (optional) - gas price in Wei to use when sending the bid.

### Processing each bidding model output and submitting bids

#### Sample model output for Fixed Discount Collateral Auction
   **Collateral price is determined by the fixed discount percentage, so only `gasPrice` is supported for fixed discount
     collateral auctions.**

A sample message sent from the fixed discount model to the keeper may look like:
```json
{"gasPrice": 70000000000}
```

#### Sample model output from Debt Auction bidding model

A sample message sent from the debt model to the keeper may look like:

`price` is `PROT/System Coin` price
```json
{"price": "250.0", "gasPrice": 70000000000}
```

#### Sample model output from Surplus Auction bidding model

A sample message sent from the debt model to the keeper may look like:

`price` is `PROT/System Coin` price
```json
{"price": "150.0"}
```

Any messages writen by a _bidding model_ to **stderr** will be passed through by the keeper to its logs.
This is the most convenient way of implementing logging from _bidding models_.

**Currently no utility is provided to prevent you from bidding at an unprofitable price.**

### Simplest possible fixed discount collateral auction bidding model

```
#!/usr/bin/env bash
while true; do
  echo "{}"
  sleep 120                   
done
```

Gas price is optional for fixed discount models. If you want to start with a fixed gas price, you can add it like this:

```
#!/usr/bin/env bash

while true; do
  echo "{\"gasPrice\": \"70000000000\"}"    # put your desired gas price in Wei here
  sleep 120                                 # locking the gas price for n seconds
done
```

The model produces price(s) for the keeper. After the `sleep` period. the keeper will restart the price model and read new price(s).  
Consider this your price update interval.

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
`liquidateSAFE`, start a new surplus or debt auction in response to opportunities regardless of whether or not your RAI or
protocol token balance is sufficient to participate.  This too imposes a gas fee.
* Liquidating SAFEs to start new collateral auctions is an expensive operation.  To do so without a subgraph
subscription, the keeper initializes a cache of safe state by scraping event logs from the chain.  The keeper will then
continuously refresh safe state to detect undercollateralized SAFEs.
   * Despite batching log queries into multiple requests, Geth nodes are generally unable to initialize the safe state
   cache in a reasonable amount of time.  As such, Geth is not recommended for liquidating SAFEs.
   * To manage resources, it is recommended to run separate keepers using separate accounts to bite (`--start-auctions-only`)
   and bid (`--bid-only`).


For some known Ubuntu and macOS issues see the [pyflex](https://github.com/reflexer-labs/pyflex) README.

# Usage

Run `bin/auction-keeper -h` without arguments to see an up-to-date list of arguments and usage information.

## General
`--type collateral|surplus|debt`
  A keeper can only participate in one type of auction
  
`--collateral-type NAME`
  If `--type=collateral` is passed, the collateral_type must also be provided. A keeper can only bid on one collateral type.
  Note: Currently, only `ETH-A` collateral type is used.
  
`--eth-from ADDRESS`
  Address of the keeper.
  Warnings: **Do not use the same `eth-from` account on multiple keepers** as it complicates SAFEEngine inventory management and
  will likely cause nonce conflicts.  Using an `eth-from` account with an open SAFE is also discouraged.
  
`--rpc-host HOST`
   URI of ETH JSON-RPC node. 
   Default `"http://localhost:8545"`
   
`--rpc-timeout SECS`
   Default `10` 

   This keeper connects to the Ethereum network using [Web3.py](https://github.com/ethereum/web3.py) and interacts with
   the GEB using [pyflex](https://github.com/reflexer-labs/pyflex).  A connection to an Ethereum node
   (`--rpc-host`) is required.  [Parity](https://www.parity.io/ethereum/) and [Geth](https://geth.ethereum.org/) nodes are
   supported over HTTP. Websocket endpoints are not supported by `pyflex`.  A _full_ or _archive_ node is required;
   _light_ nodes are not supported.

   If you don't wish to run your own Ethereum node, third-party providers are available.  This software has been tested
   with [ChainSafe](https://chainsafe.io/) and [QuikNode](https://v2.quiknode.io/). Infura is incompatible, however, because
   it does not support the `eth_sendTransaction` RPC method which is used in pyflex.

## Gas price strategies

The following options determine the keeper's gas strategy and are mutually exclusive:

`--ethgasstation-api-key MY_API_KEY`
    Use [ethgasstation.info](https://ethgasstation.info) for gas prices
    
`--etherchain-gas-price`
    Use [etherchain.org](https://etherchain.org) for gas prices
    
`--poanetwork-gas-price`
    Use [POA Network](https://poa.network) for gas prices
    An alternate URL can be passed as `--poanetwork-url`
    
 `--fixed-gas-price GWEI`
    Use a fixed gas price in GWEI
    
 If none of these options is given or the gas API produces not result, the keeper will use gas price from your node.
 
## Other gas options

`--gas-initial-multiplier MULTIPLIER`
   When using an API source for initial gas price, tunes initial gas price. 
   Ignored when using `--fixed-gas-price` or no strategy is given
   default `1.0`
   
`--gas-reactive-multiplier MULTIPLIER`
   Every 30 seconds, a transaction's gas price will be multiplied by this value until it is mined or `--gas-maxiumum` is reached.
   Not used if `gasPrice` is passed from your bidding model. 
   Note: [Parity](https://wiki.parity.io/Transactions-Queue#dropping-conditions), as of this writing, requires a
         minimum gas increase of `1.125` to propagate transaction replacement; this should be treated as a minimum
         value unless you want replacements to happen less frequently than 30 seconds (2+ blocks).
   default `1.125`
   
`--gas-maximum GWEI`
   Maximum value for gas price

## Accounting options

By default the keeper `join`s system coins to `SAFEEngine` on startup and `exit`s system coin and collateral upon shutdown.
The keeper provides facilities for managing `SAFEEngine` balances, which may be turned off to manage manually.

`--keep-system-coin-in-safe-engine-on-exit`
   Do not `exit` system coin on shutdown
   
`--keep-collateral-in-safe-engine-on-exit`
   Do not `exit` collateral on shutdown
   
`--return-collateral-interval SECS`
   Interval to `exit` won collateral to auction-keeper. Pass `0` to disable completely.
   default `300`
   
`--safe-engine-system-coin-target  ALL|<integer>` 
   Amount of system-coin the keeper will try to keep in the `SAFEEngine` through rebalancing with `join`s and `exit`s.
   By default, there is no target.

  Rebalance Notes:
    Rebalances do not account for system coins moved from the `SAFEEngine` to an auction contract for an active bid.  
    System coins are rebalanced per `--safe-engine-system-coin-target` when:
       - The keeper starts up
       - `SAFEEngine` balance is insufficient to place a bid
       - An auction is settled
       
     To avoid transaction spamming, small "dusty" system coins balances will be ignored (until the keeper exits, if so configured).

## Managing resources

### Retrieving SAFE

To start collateral auctions, the keeper needs a list of SAFEs and the collateralization ratio of each safe.  There are
two ways to retrieve the list of SAFEs:

`--from-block BLOCK_NUMBER`
   Scrape the chain for `ModifySAFECollateralization` events, starting at `BLOCK_NUMBER`
   Set this to the block where the first safe was created. After startup, only new blocks will be queried.
   NOTE: This can take significant time as the system matures.
   NOTE: To manage performance for debt auctions, periodically adjust `--from-block` to the block where the first liquidation 
   which has not been `popDebtFromQueue`.
   
 `--subgraph-endpoints NODE1,NODE2`
   Comma-delimited list of [Graph](https://thegraph.com) endpoints to retrieve `ModifySAFECollateralization` events.
   If multiple endpoints are specified, they will be tried in order if a communication failure occurs.
   NOTE: Currently only supported for collateral auctions
   Example with current Reflexer Graph endpoints:
   `--graph-endpoints https://api.thegraph.com/subgraphs/name/reflexer-labs/prai-mainnet,https://subgraph.reflexer.finance/subgraphs/name/reflexer-labs/prai`
   
### Auctions

`--min-auction AUCTION_ID`
   Ignore auctions older than `AUCTION_ID` 
   
`--max-auctions NUMBER` a
   Limit the number of bidding models created to handle active auctions.  
   
 Both switches help reduce the number of _requests_ (not just transactions) made to the node.

### Sharding/Settling

Bid management can be sharded across multiple keepers by **auction id**.  If sharding, set these options

`--shards NUMBER_OF_KEEPER`
   Number of keepers you will run. Set on all keepers
   
`--shard-id SHARD_ID` 
   Set on each keeper, counting from 0.  
   For example, to configure three keepers, set `--shards 3` and assign `--shard-id 0`, `--shard-id 1`, `--shard-id 2` 
   for the three keepers.  
   Note: **Auction starts are not sharded**. For an auction contract, only one keeper should be configured to `startAuction`.


If you are sharding across multiple accounts, you may wish to have another account handle all your `settleAuction`s. 

`--settle-for <ACCOUNT1 ACCOUNT2>|NONE|ALL`
   Space-delimited list of accounts for which keeper will settle auctions or `NONE` to disable. If you'd like to donate your gas
to settle auctions for all participants, `ALL` is also supported.  
   Note: **Auction settlements are sharded**, so remove sharding configuration if running a dedicated auction settlement keeper.

### Transaction management

`--bid-delay FLOAT`

   Too many pending transactions can fill up the transaction queue, causing a subsequent transaction to be dropped.  By
   waiting a small `--bid-delay` after each bid, multiple transactions can be submitted asynchronously while still
   allowing some time for older transactions to complete, freeing up the queue.  Many parameters determine the appropriate
   amount of time to wait.  For illustration purposes, assume the queue can hold 12 transactions, and gas prices are
   reasonable.  In this environment, a bid delay of 1.2 seconds might provide ample time for transactions at the front of
   the queue to complete.  [Etherscan.io](etherscan.io) can be used to view your account's pending transaction queue.

## Testing

This project uses [pytest](https://docs.pytest.org/en/latest/) for unit testing.  Testing depends upon on a Dockerized
local testchain included in `lib\pyflex\tests\config`.

In order to be able to run tests:
```
git clone https://github.com/reflexer-labs/auction-keeper.git
cd auction-keeper
git submodule update --init --recursive
./install.sh
source _virtualenv/bin/activate
pip3 install -r requirements-dev.txt
```

You can then run all tests with:
```
./test.sh
```

## Support

<https://discord.gg/kB4vcYs>

## License

See [COPYING](https://github.com/makerdao/auction-keeper/blob/master/COPYING) file.

### Disclaimer

YOU (MEANING ANY INDIVIDUAL OR ENTITY ACCESSING, USING OR BOTH THE SOFTWARE INCLUDED IN THIS GITHUB REPOSITORY) EXPRESSLY UNDERSTAND AND AGREE THAT YOUR USE OF THE SOFTWARE IS AT YOUR SOLE RISK.
THE SOFTWARE IN THIS GITHUB REPOSITORY IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
YOU RELEASE AUTHORS OR COPYRIGHT HOLDERS FROM ALL LIABILITY FOR YOU HAVING ACQUIRED OR NOT ACQUIRED CONTENT IN THIS GITHUB REPOSITORY. THE AUTHORS OR COPYRIGHT HOLDERS MAKE NO REPRESENTATIONS CONCERNING ANY CONTENT CONTAINED IN OR ACCESSED THROUGH THE SERVICE, AND THE AUTHORS OR COPYRIGHT HOLDERS WILL NOT BE RESPONSIBLE OR LIABLE FOR THE ACCURACY, COPYRIGHT COMPLIANCE, LEGALITY OR DECENCY OF MATERIAL CONTAINED IN OR ACCESSED THROUGH THIS GITHUB REPOSITORY.
