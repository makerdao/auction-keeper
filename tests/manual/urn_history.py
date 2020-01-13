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
from datetime import datetime, timedelta
from pprint import pprint
from web3 import Web3, HTTPProvider

from auction_keeper.urn_history import UrnHistory
from pymaker import Address
from pymaker.deployment import DssDeployment


logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

print(f"Connecting to {sys.argv[1]}...")
web3 = Web3(HTTPProvider(endpoint_uri=sys.argv[1], request_kwargs={"timeout": 120}))
vulcanize_endpoint = sys.argv[2] if len(sys.argv) > 2 else None
mcd = DssDeployment.from_node(web3)
ilk = mcd.collaterals["ETH-A"].ilk
from_block = int(sys.argv[3]) if len(sys.argv) > 3 else 8928674  # example for mainnet

started = datetime.now()
uh = UrnHistory(web3, mcd, ilk, from_block, None)
urns_logs = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_logs)} urns from block {from_block} in {elapsed.seconds} seconds")

started = datetime.now()
uh = UrnHistory(web3, mcd, ilk, None, vulcanize_endpoint)
urns_vdb = uh.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns_vdb)} urns from Vulcanize in {elapsed.seconds} seconds")

mismatches = 0
missing = 0
csv = "Urn,ChainInk,ChainArt,VulcanizeInk,VulcanizeArt\n"
for key, value in urns_logs.items():
    if key in urns_vdb:
        if value.ink != urns_vdb[key].ink or value.art != urns_vdb[key].art:
            csv += f"{key.address},{value.ink},{value.art},{urns_vdb[key].ink},{urns_vdb[key].art}\n"
            mismatches += 1
    else:
        print(f"vdb is missing urn {key}")
        missing += 1

for key, value in urns_vdb.items():
    if key not in urns_logs:
        print(f"logs is missing urn {key}")
        missing += 1
with open("urn-reconciliation.csv", "w") as file:
    file.write(csv)
print(f'Observed {mismatches} mismatched urns and {missing} missing urns')
