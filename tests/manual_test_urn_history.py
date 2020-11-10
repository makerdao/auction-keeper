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
mcd = DssDeployment.from_node(web3)
collateral_type = sys.argv[1] if len(sys.argv) > 1 else "ETH-A"
ilk = mcd.collaterals[collateral_type].ilk
# on mainnet, use 8928152 for ETH-A/BAT-A; for others, use the block when the join contract was deployed/enabled
from_block = int(sys.argv[2]) if len(sys.argv) > 2 else 8928152


# Retrieve data from
started = datetime.now()
print(f"Connecting to {vulcanize_endpoint}...")
uh = TokenFlowUrnHistoryProvider(mcd, ilk, os.environ['TOKENFLOW_URL'])
urns_tf = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_tf)} urns from TokenFlow in {elapsed.seconds} seconds")

# # Retrieve data from chain
# started = datetime.now()
# print(f"Connecting to {sys.argv[1]}...")
# uh = ChainUrnHistoryProvider(web3, mcd, ilk, from_block)
# urns_logs = uh.get_urns()
# elapsed: timedelta = datetime.now() - started
# print(f"Found {len(urns_logs)} urns from block {from_block} in {elapsed.seconds} seconds")


# Retrieve data from Vulcanize
started = datetime.now()
print(f"Connecting to {vulcanize_endpoint}...")
uh = VulcanizeUrnHistoryProvider(mcd, ilk, vulcanize_endpoint, vulcanize_key)
urns_vdb = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_vdb)} urns from Vulcanize in {elapsed.seconds} seconds")
exit(0)


# Reconcile the data
mismatches = 0
missing = 0
total_art_logs = 0
total_art_vdb = 0
csv = "Urn,ChainInk,ChainArt,VulcanizeInk,VulcanizeArt\n"

for key, value in urns_logs.items():
    assert value.ilk.name == ilk.name
    if key in urns_vdb:
        if value.ink != urns_vdb[key].ink or value.art != urns_vdb[key].art:
            csv += f"{key.address},{value.ink},{value.art},{urns_vdb[key].ink},{urns_vdb[key].art}\n"
            mismatches += 1
    else:
        print(f"vdb is missing urn {key}")
        csv += f"{key.address},{value.ink},{value.art},,\n"
        missing += 1
    total_art_logs += float(value.art)

for key, value in urns_vdb.items():
    assert value.ilk.name == ilk.name
    if key not in urns_logs:
        print(f"logs is missing urn {key}")
        missing += 1
    total_art_vdb += float(value.art)

with open(f"urn-reconciliation-{collateral_type}.csv", "w") as file:
    file.write(csv)

total = max(len(urns_vdb), len(urns_logs))
print(f'Observed {mismatches} mismatched urns ({mismatches/total:.0%}) and '
      f'{missing} missing urns ({missing/total:.0%})')
print(f"Total art from logs: {total_art_logs}, from vdb: {total_art_vdb}")
