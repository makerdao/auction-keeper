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

import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional
from web3 import Web3

from pymaker import Address, Wad
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn


class UrnHistory:
    logger = logging.getLogger()
    cache_lookback = 10  # for handling block reorgs

    def __init__(self, web3: Web3, mcd: DssDeployment, ilk: Ilk, from_block: Optional[int],
                 vulcanize_endpoint: Optional[str], vulcanize_key: Optional[str]):
        assert isinstance(web3, Web3)
        assert isinstance(mcd, DssDeployment)
        assert isinstance(ilk, Ilk)
        assert isinstance(from_block, int) or from_block is None
        assert isinstance(vulcanize_endpoint, str) or vulcanize_endpoint is None
        assert from_block or vulcanize_endpoint
        if vulcanize_endpoint:
            assert isinstance(vulcanize_key, str)

        self.web3 = web3
        self.mcd = mcd
        self.ilk = ilk
        self.from_block = from_block
        self.vulcanize_endpoint = vulcanize_endpoint
        self.vulcanize_key = vulcanize_key
        self.cache_block = from_block
        self.cache = {}

    def get_urns(self) -> Dict[Address, Urn]:
        """Returns a list of urns indexed by address"""
        if self.vulcanize_endpoint:
            if not self.cache:
                self.seed_cache_from_vulcanize()
            return self.get_urns_from_past_frobs()
        else:
            return self.get_urns_from_past_frobs()

    def get_urns_from_past_frobs(self) -> Dict[Address, Urn]:
        start = datetime.now()
        urn_addresses = set()

        from_block = max(0, self.cache_block - self.cache_lookback)
        to_block = self.web3.eth.blockNumber
        frobs = self.mcd.vat.past_frobs(from_block=from_block, to_block=to_block, ilk=self.ilk)
        for frob in frobs:
            urn_addresses.add(frob.urn)

        urns = {}
        for address in urn_addresses:
            if address not in urns:
                urns[address] = (self.mcd.vat.urn(self.ilk, address))
                self.cache[address] = urns[address]

        self.logger.debug(f"Found {len(urns)} urns among {len(frobs)} frobs since block {self.cache_block} in "
                          f"{(datetime.now()-start).seconds} seconds")
        self.cache_block = to_block
        return self.cache

    def seed_cache_from_vulcanize(self) -> Dict[Address, Urn]:
        start = datetime.now()

        response = self.run_query(self.lag_query)
        self.cache_block = int(json.loads(response.text)['data']['lastStorageDiffProcessed']['nodes'][0]['blockHeight'])

        response = self.run_query(self.query)
        raw = json.loads(response.text)['data']['allUrns']['nodes']
        for item in raw:
            if item['ilkIdentifier'] == self.ilk.name:
                urn = self.urn_from_vdb_node(item)
                self.cache[urn.address] = urn
        self.logger.debug(f"Cached {len(self.cache)} urns from VulcanizeDB up to block {self.cache_block} " 
                          f"in {(datetime.now() - start).seconds} seconds")

    def run_query(self, query: str, variables=None):
        assert isinstance(query, str)
        assert isinstance(variables, dict) or variables is None

        if variables:
            body = {'query': query, 'variables': json.dumps(variables)}
        else:
            body = {'query': query}
        headers = {'Authorization': 'Basic ' + self.vulcanize_key}
        response = requests.post(self.vulcanize_endpoint, json=body, headers=headers, timeout=30)
        if not response.ok:
            error_msg = f"{response.status_code} {response.reason} ({response.text})"
            raise RuntimeError(f"Vulcanize query failed: {error_msg}")
        return response

    def urn_from_vdb_node(self, node: dict) -> Urn:
        assert isinstance(node, dict)

        address = Address(node['urnIdentifier'])
        ink = Wad(int(node['ink']))
        art = Wad(int(node['art']))

        return Urn(address, self.ilk, ink, art)

    ilk_ids = {
        "ETH-A": 1,
        "BAT-A": 5,
        "WBTC-A": 866590
    }

    query = """query {
      allUrns {
        nodes {
          urnIdentifier
          ilkIdentifier
          ink
          art
        }
      }
    }"""

    lag_query = """query {
      lastStorageDiffProcessed: allStorageDiffs(last: 1, condition: {checked: true}) {
        nodes {
          blockHeight
        }
      }
    }"""
