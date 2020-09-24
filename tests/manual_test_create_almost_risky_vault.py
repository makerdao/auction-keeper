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

from pyflex import Address, Transact
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.model import Token
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import create_almost_risky_safe, is_critical_safe


web3 = Web3(HTTPProvider(endpoint_uri=os.environ['ETH_RPC_URL'], request_kwargs={"timeout": 30}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass

logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
# reduce logspew
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

# Usage:
# python3 tests/manual_test_create_unsafe_vault [ADDRESS] [KEY] [COLLATERAL_TYPE]

geb = GfDeployment.from_node(web3)
our_address = Address(web3.eth.defaultAccount)
collateral = geb.collaterals[str(sys.argv[3])] if len(sys.argv) > 3 else geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)
token = Token(collateral.collateral.symbol(), collateral.collateral.address, collateral.adapter.decimals())
safe = geb.safe_engine.safe(collateral.collateral_type, our_address)
# geb.approve_system_coin(our_address)
# Transact.gas_estimate_for_bad_txs = 20000
osm_price = collateral.osm.peek()
redemption_price = geb.oracle_relayer.redemption_price()
action = sys.argv[4] if len(sys.argv) > 4 else "create"


def r(value, decimals=1):
    return round(float(value), decimals)

logging.info(f"{collateral_type.name:<6}: debt_floor={r(collateral_type.debt_floor)} osm_price={osm_price} safety_ratio={r(geb.oracle_relayer.safety_c_ratio(collateral_type))}")
logging.info(f"{'':<7} stability_fee={geb.tax_collector.stability_fee(collateral_type)} min_amount={token.min_amount}")


def close_repaid_safe():
    if safe.locked_collateral > Wad(0) and safe.generated_debt == Wad(0):
        delta_collateral = safe.locked_collateral * -1
        assert geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral, Wad(0)).transact()
    collateral_balance = Wad(geb.safe_engine.collateral(collateral_type, our_address))
    if collateral_balance > Wad(0):
        assert collateral.adapter.exit(our_address, collateral_balance).transact()


# This accounts for several seconds of rate accumulation between time of calculation and the transaction being mined
flub_amount = Wad(1000)

def create_almost_risky_safe():
    # Create a safe close to the liquidation ratio
    if is_critical_safe(geb.safe_engine.collateral_type(collateral.collateral_type.name), safe):
        logging.info("SAFE is already critical; no action taken")
    else:
        collateral_amount = Wad(collateral_type.debt_floor / (Rad(osm_price)/Rad(redemption_price)) * Rad(geb.oracle_relayer.safety_c_ratio(collateral_type)) * Rad(collateral_type.accumulated_rate)) + flub_amount
        logging.info(f"Opening/adjusting safe with {collateral_amount} {collateral_type.name}")
        create_almost_risky_safe(geb, collateral, collateral_amount, our_address, False)
        logging.info("Created almost risky safe")


def handle_returned_collateral():
    # Handle collateral returned to the safe after a liquidation is settled
    available_to_generate = (safe.locked_collateral * collateral_type.safety_price) - Wad(Ray(safe.generated_debt) * collateral_type.accumulated_rate)
    if available_to_generate > token.min_amount + flub_amount:
        logging.info(f"Attempting to generate {available_to_generate} system coin")
        geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, Wad(0), available_to_generate).transact()
    system_coin_balance = Wad(geb.safe_engine.system_coin(our_address)) - Wad(1)
    if system_coin_balance > token.min_amount:
        logging.info(f"Attempting to exit {system_coin_balance} system_coin")
        geb.system_coin_adapter.exit(our_address, system_coin_balance).transact()


create_almost_risky_safe()

while True:
    time.sleep(6)
    safe = geb.safe_engine.safe(collateral.collateral_type, our_address)
    debt = Ray(safe.generated_debt) * collateral_type.accumulated_rate
    if debt > Ray(0):
        collat_ratio = float(Ray(safe.locked_collateral) * Ray(osm_price) / debt)
        logging.info(f"safe has locked_collateral={r(safe.locked_collateral)} generated_debt={r(safe.generated_debt)} debt={r(debt)} and is at {collat_ratio * 100}% collateralization")
    else:
        logging.info(f"safe has locked_collateral={r(safe.locked_collateral)} generated_debt={r(safe.generated_debt)} debt={r(debt)}")

    if web3.eth.blockNumber % 33 == 0:
        geb.tax_collector.tax_single(collateral_type).transact()

    handle_returned_collateral()
