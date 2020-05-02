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

from pymaker import Address
from pymaker.deployment import DssDeployment
from pymaker.keys import register_keys
from pymaker.model import Token
from pymaker.numeric import Wad, Ray
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
collateral = mcd.collaterals[str(sys.argv[3])] if len(sys.argv) > 2 else mcd.collaterals['ETH-A']
ilk = mcd.vat.ilk(collateral.ilk.name)
urn = mcd.vat.urn(collateral.ilk, our_address)


def create_risky_vault():
    # Create a vault close to the liquidation ratio
    if not is_cdp_safe(mcd.vat.ilk(collateral.ilk.name), urn):
        print("Vault is already unsafe; no action taken")
    else:
        osm_price = collateral.pip.peek()
        print(f"dust={ilk.dust} osm_price={osm_price} mat={mcd.spotter.mat(ilk)}")
        # To make a (barely) safe urn, I expected to add 10^-8, but for some reason I need to add 10^-7
        normalized_collateral_amount = (Wad(ilk.dust) / osm_price * Wad(mcd.spotter.mat(ilk))) + Wad.from_number(0.00000050)

        # token = Token(ilk.name, collateral.gem.address, collateral.adapter.dec())
        print(f"Opening vault with {normalized_collateral_amount} {ilk.name}")
        create_risky_cdp(mcd, collateral, Wad.from_number(normalized_collateral_amount), our_address, True)
        print("Created unsafe vault")


def handle_returned_collateral():
    # Handle collateral returned to the urn
    available_to_generate = (urn.ink * ilk.spot) - Wad(Ray(urn.art) * ilk.rate)
    print(f"urn {urn.address} can generate {available_to_generate} Dai")
    if available_to_generate > Wad(1):
        mcd.vat.frob(ilk, our_address, Wad(0), available_to_generate)
        print(f"Attempting to exit {available_to_generate} Dai")
        assert mcd.dai_adapter.exit(our_address, available_to_generate).transact()


create_risky_vault()

while True:
    time.sleep(3)
    if web3.eth.blockNumber % 33 == 0:
        mcd.jug.drip(ilk).transact()

    handle_returned_collateral()
