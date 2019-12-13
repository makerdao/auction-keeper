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


import sys
from pprint import pprint
from web3 import Web3, HTTPProvider

from auction_keeper.urn_history import UrnHistory
from pymaker import Address
from pymaker.deployment import DssDeployment


print(f"Connecting to {sys.argv[1]}...")
web3 = Web3(HTTPProvider(endpoint_uri=sys.argv[1], request_kwargs={"timeout": 120}))
vulcanize_endpoint = sys.argv[2] if len(sys.argv) > 2 else None
mcd = DssDeployment.from_network(web3, "kovan")
ilk = mcd.collaterals["ETH-A"].ilk
from_block = sys.argv[3] if len(sys.argv) > 3 else 14764597  # default for Kovan only!

# past_blocks = web3.eth.blockNumber - from_block
# log_frobs = mcd.vat.past_frobs(past_blocks, ilk)
# print(f"Found {len(log_frobs)} frobs in the past {past_blocks} blocks")

uh = UrnHistory(web3, mcd, ilk, from_block, vulcanize_endpoint)
urns = uh.get_urns_from_past_frobs()
print(f"Found {len(urns)} urns from block {from_block}")
pprint(urns[:3])
