# thrifty-keeper


This repository is a fork of https://github.com/makerdao/auction-keeper.  Before using this repository, you should refer to the main instructions for understanding keeper architecture and bidding on flip auctions.

Motivation:  Flip auctions that are profitbale for bidding are typically rare but can occur at any time.  To participate in Flip auctions, you need to deposit your Dai into a bidding contract (the Vat) to enable your keeper to make a bid, but you will not be earning the DSR while your Dai is desposited in the Vat.  Therefore, this keeper provides the following updates to the original:

- Your dai is stored in the DSR by default.  If an auction is ongoing and there is a profitable bid to make, the necessary amount of DAI is removed from the DSR and deposited into the Vat to make the bid. 

- Once the auction is over, if you have won, your ETH is immediately sold for DAI (using the 0x api).  Your DAI is then redeposited in the DSR when all auctions have ended. 




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
 * **Ethgasstation** if a key is passed as `--ethgasstation-api-key` (e.g. `--ethgasstation-api-key MY_API_KEY`)  
 * **Etherchain.org** if keeper started with `--etherchain-gas-price` switch  
 * **POANetwork** if keeper started with `--poanetwork-gas-price` switch. An alternate URL can be passed as `--poanetwork-url`,
    that is useful when server hosted locally (e.g. `--poanetwork-url http://localhost:8000`)  
 * The `--fixed-gas-price` switch allows specifying a **fixed** initial price in Gwei (e.g. `--fixed-gas-price 12.4`) 
 
When using an API source for initial gas price, `--gas-initial-multiplier` (default `1.0`, or 100%) tunes the initial 
value provided by the API.  This is ignored when using `--fixed-gas-price` and when no strategy is chosen.  If no 
initial gas source is configured, or the gas price API produces no result, then the keeper will start with a price of 
10 Gwei.

Auction keeper periodically attempts to increase gas price when transactions are queueing.  Every 30 seconds, a 
transaction's gas price will be multiplied by `--gas-reactive-multiplier` (default `2.25`, or 225%) until it is mined or 
`--gas-maximum` (default 5000 Gwei) is reached.  
Note that [Parity](https://wiki.parity.io/Transactions-Queue#dropping-conditions), as of this writing, requires a 
minimum gas increase of `1.125` (112.5%) to propogate transaction replacement; this should be treated as a minimum 
value unless you want replacements to happen less frequently than 30 seconds (2+ blocks). 

This gas strategy is used by keeper in all interactions with chain.  When sending a bid, this strategy is used only 
when the model does not provide a gas price.  Unless your price model is aware of your transaction status, it is 
generally advisable to allow the keeper to manage gas prices for bids, and not supply a `gasPrice` in your model.


### Accounting

Auction contracts exclusively interact with Dai (for all auctions) and collateral (for `flip` auctions) in the `Vat`.
More explicitly:
 * Dai used to bid on auctions is withdrawn from the `Vat`.
 * Collateral and surplus Dai won at auction is placed in the `Vat`.

By default, all Dai and collateral in your `eth-from` account is `exit`ed from the Vat and added to your token balance
when the keeper is shut down.  This feature may be disabled using the `--keep-dai-in-vat-on-exit` and
`--keep-gem-in-vat-on-exit` switches respectively.  **Using an `eth-from` account with an open CDP is discouraged**,
as debt will hinder the auction contracts' ability to access your Dai, and `auction-keeper`'s ability to `exit` Dai
from the `Vat`.

**Using the `eth-from` account on multiple keepers is also discouraged** as it complicates `Vat` inventory management.
When running multiple keepers using the same account, the balance of Dai in the `Vat` will be shared across keepers.  
If using the feature, set `--vat-dai-target` to the same value on each keeper, and sufficiently high to cover total
desired exposure.

To manually control the amount of Dai in the `Vat`, pass `--keep-dai-in-vat-on-exit` and `--keep-gem-in-vat-on-exit`
switches, and do not pass the `--vat-dai-target` switch.  You may use [mcd-cli](https://github.com/makerdao/mcd-cli)
to manually `join`/`exit` Dai to/from each of your keeper accounts.  Here is an example to join 6000 Dai on a testnet,
and exit 300 Dai on Kovan, respectively:
```bash
mcd -C testnet dai join 6000
mcd -C kovan dai exit 300
```
`mcd-cli` requires installation and configuration; view the
[mcd-cli README](https://github.com/makerdao/mcd-cli#mcd-command-line-interface) for more information.

MKR used to bid on `flap` auctions is directly withdrawn from your token balance.  MKR won at `flop` auctions is
directly deposited to your token balance.


### Managing resources

#### Minimize load on your node

To start `flip` auctions, the keeper needs a list of urns and the collateralization ratio of each urn.  There are two
ways it can build this:
 * **Set `--from-block` to the block where the first urn was created** to instruct the keeper to use logs published by
    the `vat` contract to bulid a list of urns, and then check the status of each urn.  Setting this too low will
    overburden your node.
 * **Deploy a [VulcanizeDB lite instance](https://github.com/makerdao/vdb-lite-mcd-transformers) to maintain your own
    copy of urn state in PostgresQL, and then set `--vulcanize-endpoint` to your instance**.  This will conserve
    resources on your node and keeper.

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

#### Hardware and operating system resources

 * The most expensive keepers are `flip` and `flop` keepers configured to `kick` new auctions.
 * To prevent process churn, ensure your pricing model stays running for a reasonable amount of time.


## Infrastructure

This keeper connects to the Ethereum network using [Web3.py](https://github.com/ethereum/web3.py) and interacts with
the Dai Stablecoin System (DSS) using [pymaker](https://github.com/makerdao/pymaker).  A connection to an Ethereum node
(`--rpc-host`) is required.  [Parity](https://www.parity.io/ethereum/) and [Geth](https://geth.ethereum.org/) nodes are
supported over HTTP. Websocket endpoints are not supported by `pymaker`.

If you don't wish to run your own Ethereum node, third-party providers are available.  This software has been tested
with [ChainSafe](https://chainsafe.io/) and [QuikNode](https://v2.quiknode.io/). Infura is incompatible, however, because
it does not support the `eth_sendTransaction` RPC method, which is [utilized in](https://github.com/makerdao/pymaker/blob/69c7b6d869bb3bc9c4cca7b82cc6e8d435966d4b/pymaker/__init__.py#L431) pymaker.

### Limitations
When a keeper, without VulcanizeDB subscription, is allowed to `kick`, it first gathers all historically active urns by
making a single log query. The following limitation arises in this scenario:
* A Geth node will likely cause issues (in the form of a `ValueError: {'code': -32000, 'message': 'Filter not found'}`),
owing to a lack of support for large, complex filtered log queries. If a growing chain state begins to inhibit log
requests with Parity nodes, then future releases of pymaker could include log query batching.



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
