# auction-keeper manual testing

The collection of python and shell scripts herein may be used to test `auction-keeper`, `pymaker`'s auction facilities, 
and relevant smart contracts in `dss`.  Artifacts herein assume manual testing will be performed on Kovan.

## Dependencies

* Install `bc` and `jshon`
* Install [mcd-cli](https://github.com/makerdao/mcd-cli#installation)
* Configure your [environment for mcd-cli](https://github.com/makerdao/mcd-cli#configuration)
* Optionally, to avoid being prompted, set `ETH_PASSWORD` to the password for your private key.

## Testing flip auctions
The general test workflow is:
1. Procure some collateral in a vault owner account
2. Procure same Dai in a keeper account
3. Create "risky" vaults as close as possible to the liquidation ratio
4. Run `auction-keeper` configured to bite and bid
5. Periodically `drip` the `jug` to apply stability fees, causing the keeper to `bite`


### Creating a single risky vault
This can be done without `mcd-cli`, omitting most dependencies enumerated above.
`manual_test_create_unsafe_vault.py` creates one native urn for a particular account.


### Creating multiple risky vaults
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