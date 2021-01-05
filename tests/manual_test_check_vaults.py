# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2021 EdNoepel
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
from pymaker.dss import Ilk, Urn
from pymaker.numeric import Wad, Ray, Rad
from pymaker.oracles import OSM


logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger("web3").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("requests").setLevel(logging.INFO)

web3 = Web3(HTTPProvider(endpoint_uri=os.environ["ETH_RPC_URL"], request_kwargs={"timeout": 240}))

mcd = DssDeployment.from_node(web3)
collateral_type = sys.argv[1] if len(sys.argv) > 1 else "ETH-A"
ilk = mcd.collaterals[collateral_type].ilk
urn_history = None

if isinstance(sys.argv[2], int):
    from_block = int(sys.argv[2])
    urn_history = ChainUrnHistoryProvider(web3, mcd, ilk, from_block)
elif sys.argv[2] == "vulcanize":
    vulcanize_endpoint = os.environ["VULCANIZE_URL"]
    vulcanize_key = os.environ["VULCANIZE_APIKEY"]
    urn_history = VulcanizeUrnHistoryProvider(mcd, ilk, vulcanize_endpoint, vulcanize_key)
elif sys.argv[2] == "tokenflow":
    tokenflow_endpoint = os.environ['TOKENFLOW_URL']
    tokenflow_key = os.environ['TOKENFLOW_APIKEY']
    urn_history = TokenFlowUrnHistoryProvider(web3, mcd, ilk, tokenflow_endpoint, tokenflow_key)

started = datetime.now()
urns = urn_history.get_urns()
elapsed: timedelta = datetime.now() - started
print(f"Found {len(urns)} urns in {elapsed.seconds} seconds")

rate = ilk.rate
osm: OSM = mcd.collaterals[collateral_type].pip
mat = mcd.spotter.mat(ilk)

print(f"{ilk.name} current={osm.peek()} next={osm.peep()} rate={ilk.rate} mat={mat}")

for urn in urns.values():
    if urn.art == Wad(0):
        continue
    debt = Ray(urn.art) * rate
    liquidation_price = float(debt * mat / Ray(urn.ink))
    safe_at_spot = Ray(urn.ink) * ilk.spot >= Ray(urn.art) * rate
    safe_at_current = float(osm.peek()) >= liquidation_price
    safe_at_next = float(osm.peep()) >= liquidation_price

    if not safe_at_spot:
        print(f"Urn {urn.address} is undercollateralized at current spot with ink={urn.ink}, art={urn.art}")
    elif not safe_at_current:
        print(f"Urn {urn.address} is undercollateralized at current OSM price with ink={urn.ink}, art={urn.art}")
    elif not safe_at_next:
        print(f"Urn {urn.address} is undercollateralized at next OSM price with ink={urn.ink}, art={urn.art}")
