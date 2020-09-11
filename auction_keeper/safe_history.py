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

from pyflex import Address, Wad
from pyflex.deployment import GfDeployment
from pyflex.gf import CollateralType, SAFE


class UrnHistory:
    logger = logging.getLogger()
    cache_lookback = 10  # for handling block reorgs

    def __init__(self, web3: Web3, geb: GfDeployment, collateral_type: CollateralType, from_block: Optional[int],
                 vulcanize_endpoint: Optional[str], vulcanize_key: Optional[str]):
        assert isinstance(web3, Web3)
        assert isinstance(geb, GfDeployment)
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(from_block, int) or from_block is None
        assert isinstance(vulcanize_endpoint, str) or vulcanize_endpoint is None
        assert isinstance(vulcanize_key, str) or vulcanize_key is None
        assert from_block or vulcanize_endpoint

        self.web3 = web3
        self.geb = geb
        self.collateral_type = ilk
        self.from_block = from_block
        self.vulcanize_endpoint = vulcanize_endpoint
        self.vulcanize_key = vulcanize_key
        self.cache_block = from_block
        self.cache = {}

    def get_safes(self) -> Dict[Address, Urn]:
        """Returns a list of urns indexed by address"""
        if self.vulcanize_endpoint:
            return self.get_urns_from_vulcanize()
        else:
            return self.get_urns_from_past_frobs()

    def get_safes_from_past_frobs(self) -> Dict[Address, Urn]:
        start = datetime.now()
        safe_addresses = set()

        # Get a unique list of safe addresses
        from_block = max(0, self.cache_block - self.cache_lookback)
        to_block = self.web3.eth.blockNumber
        frobs = self.geb.safe_engine.past_frobs(from_block=from_block, to_block=to_block, collateral_type=self.ilk)
        for frob in frobs:
            safe_addresses.add(frob.safe)

        # Update state of already-cached safes
        for address, safe in self.cache.items():
            self.cache[address] = self.geb.safe_engine.safe(self.collateral_type, address)

        # Cache state of newly discovered safes
        for address in safe_addresses:
            if address not in self.cache:
                self.cache[address] = self.geb.safe_engine.safe(self.collateral_type, address)

        self.logger.debug(f"Updated {len(self.cache)} safes in {(datetime.now()-start).seconds} seconds")
        self.cache_block = to_block
        return self.cache

    def get_safes_from_vulcanize(self) -> Dict[Address, Urn]:
        start = datetime.now()

        response = self.run_query(self.lag_query)
        self.cache_block = int(json.loads(response.text)['data']['lastStorageDiffProcessed']['nodes'][0]['blockHeight'])

        response = self.run_query(self.init_query)
        raw = json.loads(response.text)['data']['allUrns']['nodes']
        for item in raw:
            if item['collateralTypeIdentifier'] == self.ilk.name:
                safe = self.safe_from_vdb_node(item)
                self.cache[safe.address] = safe
        self.logger.debug(f"Found {len(self.cache)} safes from VulcanizeDB up to block {self.cache_block} " 
                          f"in {(datetime.now() - start).seconds} seconds")

        start = datetime.now()
        from_block = max(0, self.cache_block - self.cache_lookback)
        response = self.run_query(self.recent_changes_query, {"fromBlock": from_block})
        parsed_data = json.loads(response.text)['data']

        frobs_for_collateral_type = self.filter_safe_nodes_by_ilk(parsed_data['allVatFrobs']['nodes'])
        recent_frobs = [item['rawUrnByUrnId']['identifier'] for item in frobs_for_collateral_type]
        bites_for_collateral_type = self.filter_safe_nodes_by_ilk(parsed_data['allRawBites']['nodes'])
        recent_bites = [item['rawUrnByUrnId']['identifier'] for item in bites_for_collateral_type]
        forks_for_collateral_type = self.filter_nodes_by_ilk(parsed_data['allVatForks']['nodes'])
        recent_forks = [item['src'] for item in forks_for_collateral_type] + [item['dst'] for item in forks_for_ilk]
        assert isinstance(recent_frobs, list)
        assert isinstance(recent_bites, list)
        assert isinstance(recent_forks, list)
        recent_changes = set(recent_frobs + recent_bites + recent_forks)
        for safe in recent_changes:
            address = Address(safe)
            self.cache[address] = self.geb.safe_engine.safe(self.collateral_type, address)

        current_block = int(parsed_data['lastBlock']['nodes'][0]['blockNumber'])
        self.logger.debug(f"Updated {len(recent_changes)} safes from block {from_block} to {current_block} "
                          f"in {(datetime.now() - start).seconds} seconds")
        self.cache_block = current_block
        return self.cache

    def run_query(self, query: str, variables=None):
        assert isinstance(query, str)
        assert isinstance(variables, dict) or variables is None

        if variables:
            body = {'query': query, 'variables': json.dumps(variables)}
        else:
            body = {'query': query}
        headers = {'Authorization': 'Basic ' + self.vulcanize_key} if self.vulcanize_key else None
        response = requests.post(self.vulcanize_endpoint, json=body, headers=headers, timeout=30)
        if not response.ok:
            error_msg = f"{response.status_code} {response.reason} ({response.text})"
            raise RuntimeError(f"Vulcanize query failed: {error_msg}")
        return response

    def filter_safe_nodes_by_collateral_type(self, nodes: list):
        assert isinstance(nodes, list)
        return list(filter(lambda item: item['rawUrnByUrnId']['rawCollateralTypeByCollateralTypeId']['identifier'] == self.collateral_type.name, nodes))

    def filter_nodes_by_collateral_type(self, nodes: list):
        assert isinstance(nodes, list)
        return list(filter(lambda item: item['rawCollateralTypeByCollateralTypeId']['identifier'] == self.collateral_type.name, nodes))

    def safe_from_vdb_node(self, node: dict) -> Urn:
        assert isinstance(node, dict)

        address = Address(node['safeIdentifier'])
        ink = Wad(int(node['ink']))
        art = Wad(int(node['art']))

        return Urn(address, self.collateral_type, ink, art)

    init_query = """query {
      allUrns {
        nodes {
          safeIdentifier
          collateralTypeIdentifier
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

    recent_changes_query = """query($fromBlock: BigInt) {
      allVatFrobs(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawUrnByUrnId {
            rawCollateralTypeByCollateralTypeId {
              identifier
            }
            identifier
          }
        }
      }
      allRawBites(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawUrnByUrnId {
            rawCollateralTypeByCollateralTypeId {
              identifier
            }
            identifier
          }
        }
      }
      allVatForks(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawCollateralTypeByCollateralTypeId {
              identifier
          }
          src
          dst
        }
      }
      lastBlock: allHeaders(last: 1) {
        nodes {
          blockNumber
        }
      }
    }"""
