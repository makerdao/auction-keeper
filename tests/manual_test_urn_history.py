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
import sys
import time
from datetime import datetime, timedelta
from pprint import pprint
from web3 import Web3, HTTPProvider

from auction_keeper.urn_history import UrnHistory
from auction_keeper.urn_history_old_vdb import UrnHistoryOldVdb
from pymaker import Wad
from pymaker.deployment import DssDeployment


logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

web3 = Web3(HTTPProvider(endpoint_uri=sys.argv[1], request_kwargs={"timeout": 240}))
vulcanize_endpoint = sys.argv[2]
vulcanize_key = sys.argv[3]
mcd = DssDeployment.from_node(web3)
collateral_type = sys.argv[4] if len(sys.argv) > 4 else "ETH-A"
ilk = mcd.collaterals[collateral_type].ilk
from_block = int(sys.argv[5]) if len(sys.argv) > 5 else 8928152  # 8928152 example for mainnet, 9989448 for WBTC


def wait(blocks_to_wait: int, uh: UrnHistory):
    while blocks_to_wait > 0:
        print(f"Testing cache for another {blocks_to_wait} blocks")
        time.sleep(13.4)
        uh.get_urns()
        blocks_to_wait -= 1


# Retrieve data from chain
started = datetime.now()
print(f"Connecting to {sys.argv[1]}...")
uh = UrnHistory(web3, mcd, ilk, from_block, None, None)
urns_logs = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_logs)} urns from block {from_block} in {elapsed.seconds} seconds")
wait(1500, uh)


# Retrieve data from Vulcanize
started = datetime.now()
print(f"Connecting to {vulcanize_endpoint}...")
uh = UrnHistory(web3, mcd, ilk, None, vulcanize_endpoint, vulcanize_key)
urns_vdb = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_vdb)} urns from Vulcanize in {elapsed.seconds} seconds")


# Retrieve data from old Vulcanize
started = datetime.now()
print("Connecting to old VDB")
uh = UrnHistoryOldVdb(web3, mcd, ilk)
urns_vdb_old = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_vdb_old)} urns from old Vulcanize in {elapsed.seconds} seconds")
# urns_vdb_old = {}


# Reconcile the data
mismatches = 0
missing = 0
total_art_logs = 0
total_art_vdb = 0
csv = "Urn,ChainInk,ChainArt,VulcanizeInk,VulcanizeArt"
csv += ",OldVdbInk,OldVdbArt\n" if len(urns_vdb_old) > 0 else '\n'

for key, value in urns_logs.items():
    assert value.ilk.name == ilk.name
    if key in urns_vdb:
        if value.ink != urns_vdb[key].ink or value.art != urns_vdb[key].art:
            csv += f"{key.address},{value.ink},{value.art},{urns_vdb[key].ink},{urns_vdb[key].art}"
            if key in urns_vdb_old:
                csv += f",{urns_vdb_old[key].ink},{urns_vdb_old[key].art}"
            else:
                csv += ",,"
            csv += "\n"
            mismatches += 1
    else:
        print(f"vdb is missing urn {key}")
        if key in urns_vdb_old:
            csv += f"{key.address},{value.ink},{value.art},{urns_vdb_old[key].ink},{urns_vdb_old[key].art}\n"
        else:
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
