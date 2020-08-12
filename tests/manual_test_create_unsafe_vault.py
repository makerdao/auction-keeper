# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 EdNoepel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import os
import sys
import time
from web3 import Web3, HTTPProvider

from pymaker import Address, Transact
from pymaker.deployment import DssDeployment
from pymaker.keys import register_keys
from pymaker.model import Token
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import create_risky_cdp, is_cdp_safe


web3 = Web3(HTTPProvider(endpoint_uri=os.environ['ETH_RPC_URL'], request_kwargs={"timeout": 30}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass

logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
# reduce logspew
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

mcd = DssDeployment.from_node(web3)
our_address = Address(web3.eth.defaultAccount)
collateral = mcd.collaterals[str(sys.argv[3])] if len(sys.argv) > 3 else mcd.collaterals['ETH-A']
ilk = mcd.vat.ilk(collateral.ilk.name)
token = Token(collateral.gem.symbol(), collateral.gem.address, collateral.adapter.dec())
urn = mcd.vat.urn(collateral.ilk, our_address)
# mcd.approve_dai(our_address)
# Transact.gas_estimate_for_bad_txs = 20000
osm_price = collateral.pip.peek()


def r(value, decimals=1):
    return round(float(value), decimals)

logging.info(f"{ilk.name:<6}: dust={r(ilk.dust)} osm_price={osm_price} mat={r(mcd.spotter.mat(ilk))}")
logging.info(f"{'':<7} duty={mcd.jug.duty(ilk)} min_amount={token.min_amount}")


def close_repaid_urn():
    if urn.ink > Wad(0) and urn.art == Wad(0):
        dink = urn.ink * -1
        assert mcd.vat.frob(ilk, our_address, dink, Wad(0)).transact()
    gem_balance = Wad(mcd.vat.gem(ilk, our_address))
    if gem_balance > Wad(0):
        assert collateral.adapter.exit(our_address, gem_balance).transact()


# This accounts for several seconds of rate accumulation between time of calculation and the transaction being mined
flub_amount = Wad(1000)


def create_risky_vault():
    # Create a vault close to the liquidation ratio
    if not is_cdp_safe(mcd.vat.ilk(collateral.ilk.name), urn):
        logging.info("Vault is already unsafe; no action taken")
    else:
        collateral_amount = Wad(ilk.dust / Rad(osm_price) * Rad(mcd.spotter.mat(ilk)) * Rad(ilk.rate)) + flub_amount
        logging.info(f"Opening/adjusting vault with {collateral_amount} {ilk.name}")
        create_risky_cdp(mcd, collateral, collateral_amount, our_address, False)
        logging.info("Created risky vault")


def handle_returned_collateral():
    # Handle collateral returned to the urn after a liquidation is dealt
    available_to_generate = (urn.ink * ilk.spot) - Wad(Ray(urn.art) * ilk.rate)
    if available_to_generate > token.min_amount + flub_amount:
        logging.info(f"Attempting to generate {available_to_generate} Dai")
        mcd.vat.frob(ilk, our_address, Wad(0), available_to_generate).transact()
    dai_balance = Wad(mcd.vat.dai(our_address)) - Wad(1)
    if dai_balance > token.min_amount:
        logging.info(f"Attempting to exit {dai_balance} Dai")
        mcd.dai_adapter.exit(our_address, dai_balance).transact()


create_risky_vault()



while True:
    time.sleep(6)
    urn = mcd.vat.urn(collateral.ilk, our_address)
    debt = Ray(urn.art) * ilk.rate
    if debt > Ray(0):
        collat_ratio = float(Ray(urn.ink) * Ray(osm_price) / debt)
        logging.info(f"urn has ink={r(urn.ink)} art={r(urn.art)} debt={r(debt)} and is at {collat_ratio * 100}% collateralization")
    else:
        logging.info(f"urn has ink={r(urn.ink)} art={r(urn.art)} debt={r(debt)}")

    if web3.eth.blockNumber % 33 == 0:
        mcd.jug.drip(ilk).transact()

    handle_returned_collateral()
