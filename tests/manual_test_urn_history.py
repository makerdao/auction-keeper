# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel
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
from datetime import datetime, timedelta
from web3 import Web3, HTTPProvider

from auction_keeper.urn_history import ChainUrnHistoryProvider
from auction_keeper.urn_history_tokenflow import TokenFlowUrnHistoryProvider
from auction_keeper.urn_history_vulcanize import VulcanizeUrnHistoryProvider
from pymaker.deployment import DssDeployment


logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

web3 = Web3(HTTPProvider(endpoint_uri=os.environ["ETH_RPC_URL"], request_kwargs={"timeout": 240}))
vulcanize_endpoint = os.environ["VULCANIZE_URL"]
vulcanize_key = os.environ["VULCANIZE_APIKEY"]
tokenflow_endpoint = os.environ['TOKENFLOW_URL']
tokenflow_key = os.environ['TOKENFLOW_APIKEY']
mcd = DssDeployment.from_node(web3)
collateral_type = sys.argv[1] if len(sys.argv) > 1 else "ETH-A"
ilk = mcd.collaterals[collateral_type].ilk
# on mainnet, use 8928152 for ETH-A/BAT-A; for others, use the block when the join contract was deployed/enabled
from_block = int(sys.argv[2]) if len(sys.argv) > 2 else None
urns_chain = None
urns_vdb = None
urns_tf = None


# Retrieve data from Vulcanize
if vulcanize_endpoint:
    started = datetime.now()
    print(f"Connecting to {vulcanize_endpoint}...")
    uh = VulcanizeUrnHistoryProvider(mcd, ilk, vulcanize_endpoint, vulcanize_key)
    urns_vdb = uh.get_urns()
    elapsed: timedelta = datetime.now() - started
    print(f"Found {len(urns_vdb)} urns from Vulcanize in {elapsed.seconds} seconds")
    assert len(urns_vdb) > 0

# Retrieve data from TokenFlow
if tokenflow_endpoint:
    started = datetime.now()
    print(f"Connecting to {tokenflow_endpoint}...")
    uh = TokenFlowUrnHistoryProvider(web3, mcd, ilk, tokenflow_endpoint, tokenflow_key)
    urns_tf = uh.get_urns()
    elapsed: timedelta = datetime.now() - started
    print(f"Found {len(urns_tf)} urns from TokenFlow in {elapsed.seconds} seconds")
    assert len(urns_tf) > 0

# Retrieve data from chain
if from_block:
    started = datetime.now()
    print(f"Connecting to {sys.argv[1]}...")
    uh = ChainUrnHistoryProvider(web3, mcd, ilk, from_block)
    urns_chain = uh.get_urns()
    elapsed: timedelta = datetime.now() - started
    print(f"Found {len(urns_chain)} urns from block {from_block} in {elapsed.seconds} seconds")
    assert len(urns_chain) > 0


def reconcile(left: dict, right: dict, left_name="Left", right_name="Right"):
    mismatches = 0
    missing = 0
    total_ink_left = 0
    total_ink_right = 0
    total_art_left = 0
    total_art_right = 0
    csv = f"Urn,{left_name}Ink,{left_name}Art,{right_name}Ink,{right_name}Art,DiffInk,DiffArt\n"

    for key, value in left.items():
        assert value.ilk.name == ilk.name
        if key in right:
            if value.ink != right[key].ink or value.art != right[key].art:
                csv += f"{key.address},{value.ink},{value.art},{right[key].ink},{right[key].art}," \
                       f"{value.ink-right[key].ink},{value.art-right[key].art}\n"
                mismatches += 1
        else:
            # print(f"{right_name} is missing urn {key}")
            csv += f"{key.address},{value.ink},{value.art},,,,\n"
            missing += 1
        total_ink_left += float(value.ink)
        total_art_left += float(value.art)
    
    for key, value in right.items():
        assert value.ilk.name == ilk.name
        if key not in left:
            # print(f"{left_name} is missing urn {key}")
            csv += f"{key.address},,,{value.ink},{value.art},,\n"
            missing += 1
        total_ink_right += float(value.ink)
        total_art_right += float(value.art)

    with open(f"urn-reconciliation-{collateral_type}.csv", "w") as file:
        file.write(csv)

    total = max(len(left), len(right))
    print(f'Observed {mismatches} mismatched urns ({mismatches/total:.0%}) and '
          f'{missing} missing urns ({missing/total:.0%})')
    print(f"Total ink from {left_name}: {total_ink_left}, from {right_name}: {total_ink_right}, "
          f"difference: {total_ink_left-total_ink_right}")
    print(f"Total art from {left_name}: {total_art_left}, from {right_name}: {total_art_right}, "
          f"difference: {total_art_left-total_art_right}")


if from_block:
    reconcile(urns_chain, urns_tf, "Chain", "TokenFlow")
elif urns_tf:
    reconcile(urns_vdb, urns_tf, "Vulcanize", "TokenFlow")
else:
    reconcile(urns_chain, urns_vdb, "Chain", "Vulcanize")
