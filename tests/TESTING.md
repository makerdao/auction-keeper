# auction-keeper manual testing

The collection of python and shell scripts herein may be used to test `auction-keeper`, `pymaker`'s auction facilities, 
and relevant smart contracts in `dss`.

## Dependencies

* Install `bc` and `jshon`
* Install [mcd-cli](https://github.com/makerdao/mcd-cli#installation)
* Configure your [environment for mcd-cli](https://github.com/makerdao/mcd-cli#configuration)
* Optionally, to avoid being prompted, set `ETH_PASSWORD` to the password for your private key.

## Testing flip auctions
From the root directory of this repository, with your virtual env sourced:
1. Set up your python path with `export PYTHONPATH=$PYTHONPATH:./lib/pymaker:./lib/pygasprice-client`.
2. Run `mcd -C kovan --ilk=ETH-A poke` (replacing `ETH-A` with the desired collateral type) to poke the spot price.
3. Run `python3 tests/manual_test_get_unsafe_vault_params.py` to determine `ink` (collateral) and `art` (Dai) for 
  creating a vault right at the liquidation ratio.  You may pass collateral type as a parameter (defaults to `ETH-A`).
  You may pass a desired amount of debt as a second parameter to test larger liquidations (defaults to dust limit).
4. Run `tests/create-vault.sh` passing these values of `ink` and `art` to create a risky vault.  You'll likely want to 
  round up slightly to ensure there's enough collateral to generate the specified amount of Dai.  Should the `draw` 
  fail because the vault would be unsafe, call `mcd -C kovan cdp [VAULT ID] draw [ART]` drawing slightly less Dai.
5. `drip` the `jug` periodically to apply stability fees, eventually creating an opportunity for the keeper to `bite`.

At any time, you may run `mcd -C kovan --ilk=ETH-A cdp ls` to see a list of your vaults and 
`mcd -C kovan --ilk=ETH-A cdp [VAULT ID] urn` to check size and collateralization of each.