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
import time
from datetime import datetime, timedelta
from web3 import Web3, HTTPProvider

from auction_keeper.safe_history import SAFEHistory
from pyflex.deployment import GfDeployment


logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.INFO)
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

web3 = Web3(HTTPProvider(endpoint_uri=os.environ["ETH_RPC_URL"], request_kwargs={"timeout": 240}))
GRAPH_ENDPOINTS = ['https://api.thegraph.com/subgraphs/name/reflexer-labs/rai-kovan',
                   'https://subgraph-kovan.reflexer.finance/subgraphs/name/reflexer-labs/rai']
geb = GfDeployment.from_node(web3)
collateral_type = sys.argv[1] if len(sys.argv) > 1 else "ETH-A"
collateral_type= geb.collaterals[collateral_type].collateral_type

# on kovan 0.9.0 use 21461453
from_block = int(sys.argv[2]) if len(sys.argv) > 2 else 21461453


def wait(minutes_to_wait: int, sh: SAFEHistory):
    while minutes_to_wait > 0:
        time.sleep(2)
        print(f"Testing cache for another {minutes_to_wait:.2f} minutes")
        state_update_started = datetime.now()
        sh.get_safes()
        minutes_elapsed = (datetime.now() - state_update_started).seconds / 60
        minutes_to_wait -= minutes_elapsed

# Retrieve data from chain
started = datetime.now()
print(f"Connecting to node...")
sh = SAFEHistory(web3, geb, collateral_type, from_block, None)
safes_logs = sh.get_safes()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(safes_logs)} safes from block {from_block} in {elapsed.seconds} seconds")

wait(1, sh)

# Retrieve data from the Graph
started = datetime.now()
print(f"Connecting to graph_endpoint...")
sh = SAFEHistory(web3, geb, collateral_type, from_block, GRAPH_ENDPOINTS)
safes_graph = sh.get_safes()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(safes_graph)} safes from the Graph in {elapsed.seconds} seconds")

wait(1, sh)

# Reconcile the data
mismatches = 0
missing = 0
total_generated_debt_logs = 0
total_generated_debt_graph = 0
csv = "SAFE,ChainLockedCollateral,ChainGeneratedDebt,GraphLockedCollateral,GraphGeneratedDebt\n"

for key, value in safes_logs.items():
    assert value.collateral_type.name == collateral_type.name
    if key in safes_graph:
        if value.locked_collateral != safes_graph[key].locked_collateral or value.generated_debt != safes_graph[key].generated_debt:
            csv += f"{key.address},{value.locked_collateral},{value.generated_debt},{safes_graph[key].locked_collateral},{safes_graph[key].generated_debt}\n"
            mismatches += 1
    else:
        print(f"the graph is missing safe {key}")
        csv += f"{key.address},{value.locked_collateral},{value.generated_debt},,\n"
        missing += 1
    total_generated_debt_logs += float(value.generated_debt)

for key, value in safes_graph.items():
    assert value.collateral_type.name == collateral_type.name
    if key not in safes_logs:
        print(f"logs is missing safe {key}")
        missing += 1
    total_generated_debt_graph += float(value.generated_debt)

with open(f"safe-reconciliation-{collateral_type}.csv", "w") as file:
    file.write(csv)

total = max(len(safes_graph), len(safes_logs))
print(f'Observed {mismatches} mismatched safes ({mismatches/total:.0%}) and '
      f'{missing} missing safes ({missing/total:.0%})')
print(f"Total generated_debt from logs: {total_generated_debt_logs}, from graph: {total_generated_debt_graph}")
