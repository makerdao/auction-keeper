# auction-keeper manual testing

The collection of python and shell scripts herein may be used to test `auction-keeper`, `pymaker`'s auction facilities, 
and relevant smart contracts in `dss`.

## Starting a Testchain
The included `docker-compose.yml` creates two containers from an image named `mcd-auction-testchain`.  Two containers 
are needed because the keeper requires at least two peers.  This testchain should be set up with meaningful `ttl` and 
`tau` values to facilitate testing without waiting eons for bids to expire.  A smaller `bump` may be desirable for 
testing `flap` auctions, as it would take time for rates to accumulate on a fresh testchain.  The testchain may be 
reset by stopping and deleting both containers.


## Testing Scenarios

### Python scripts

* `create_unsafe_cdp.py` does exactly what it's name suggests; it creates a single CDP close to the liquidation ratio, 
and then slightly drops the price of ETH such that the CDP becomes undercollateralized.  If run on an 
already-undercollateralized CDP, it will submit no transaction.  In either case, it prints a message stating whether an 
action was performed.  This may be used to test `flip` auctions as well as build debt for `flop` auctions.
* `create_surplus.py` creates a CDP and then calls `jug.drip` to establish a surplus.  The age of the testchain 
and amount of collateral placed in this CDP determines how much surplus is generated.
* `print.py` provides status information based on the parameter passed:
  * `--auctions` prints the most recent bid for each active auction
  * `--balances` shows the balance of surplus and debt
* `purchase_dai.py` creates a CDP using another address and transfers Dai to the keeper account for bidding on `flip` 
and `flop` auctions.  The amount of Dai to purchase is passed as the only argument.
* `mint_mkr.py` generates MKR tokens for bidding on `flap` auctions.  The amount of MKR to mint is passed as the only 
argument.

Here's an example of running a script manually from the repository root:
```bash
export PYTHONPATH=$PYTHONPATH:.:lib/pymaker
python3 tests/manual/mint_mkr.py 1.0
```

You'll likely want to run `purchase_dai.py` and `mint_mkr.py` to procure tokens before starting your keepers.

### Shell scripts

`test-[scenario]` scripts make use of the python scripts above.  Since the keepers automatically shut down if no block 
is mined in several minutes, these scripts generally have a loop which transacts every 13 seconds to simulate a "real" 
chain.

`create-cdp.sh` and `create-cdps.sh` make use of `mcd-cli` to create CDPs using the CDP Manager.  This allows our tests 
to create a large number of CDPs despite only having a handful of accounts on the testchain.  One way to configure 
`mcd-cli` with the testchain:
* Copy the appropriate `addresses.json` from `lib/pymaker/config` to `~/.dapp/testnet/8545/config/addresses.json`
* Copy key files to `~/.dapp/testnet/8545/keystore`
* Modify the _testnet_ section of `libexec/mcd/mcd` to point to the correct IP
* Redeploy `mcd-cli` using _automake_: `sudo make uninstall; sudo make install`


## Starting Keepers

`start-[auction type]-keeper.sh` runs a keeper for a particular auction type.  To test flip auctions for multiple 
collateral types, `start-flip-keeper.sh` could be split out into multiple files, or an argument added for the 
`FLIPPER_ADDRESS` for that collateral type.  As-is, these scripts take two arguments:
* *model* is the name of the script to serve as price model.  Several fixed price model scripts are included, as 
documented below.
* *id* is used merely to log output to different files for each keeper; the string is a component of the log file name.

`model_[price].sh` scripts serve as fixed price models for the keeper.  They are invoked directly by the keeper, and 
are not useful to execute explicitly.

### Multiplexing Terminals
Since keepers communicate with models using stdin/stdout, running in a terminal window is prudent.  To run and monitor 
multiple keepers with `tmux`:
 * `tmux new -s auctions` to create a new session
 * `Ctrl-B %` and `Ctrl-B "` to split into the desired number of panes
 * `Ctrl-B :` with the command `select-layout tiled` to arrange panes meaningfully
 * To change to the appropriate directory and source the virtualenv, `Ctrl-B :` with the command 
 `setw synchronize-panes on` is helpful.