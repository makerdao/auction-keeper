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
from pyflex.gf import CollateralType, Safe


class SafeHistory:
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
        self.collateral_type = collateral_type
        self.from_block = from_block
        self.vulcanize_endpoint = vulcanize_endpoint
        self.vulcanize_key = vulcanize_key
        self.cache_block = from_block
        self.cache = {}

    def get_safes(self) -> Dict[Address, Safe]:
        """Returns a list of safes indexed by address"""
        if self.vulcanize_endpoint:
            return self.get_safes_from_vulcanize()
        else:
            return self.get_safes_from_past_frobs()

    def get_safes_from_past_frobs(self) -> Dict[Address, Safe]:
        start = datetime.now()
        safe_addresses = set()

        # Get a unique list of safe addresses
        from_block = max(0, self.cache_block - self.cache_lookback)
        to_block = self.web3.eth.blockNumber
        mods = self.geb.safe_engine.past_safe_modifications(from_block=from_block, to_block=to_block, collateral_type=self.collateral_type)
        for mods in mods:
            safe_addresses.add(mod.safe)

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

    def get_safes_from_vulcanize(self) -> Dict[Address, Safe]:
        start = datetime.now()

        response = self.run_query(self.lag_query)
        self.cache_block = int(json.loads(response.text)['data']['lastStorageDiffProcessed']['nodes'][0]['blockHeight'])

        response = self.run_query(self.init_query)
        raw = json.loads(response.text)['data']['allSafes']['nodes']
        for item in raw:
            if item['collateralTypeIdentifier'] == self.collateral_type.name:
                safe = self.safe_from_vdb_node(item)
                self.cache[safe.address] = safe
        self.logger.debug(f"Found {len(self.cache)} safes from VulcanizeDB up to block {self.cache_block} " 
                          f"in {(datetime.now() - start).seconds} seconds")

        start = datetime.now()
        from_block = max(0, self.cache_block - self.cache_lookback)
        response = self.run_query(self.recent_changes_query, {"fromBlock": from_block})
        parsed_data = json.loads(response.text)['data']

        mods_for_collateral_type = self.filter_safe_nodes_by_collateral_type(parsed_data['allSafeEngineMods']['nodes'])
        recent_mods = [item['rawSafeBySafeId']['identifier'] for item in mods_for_collateral_type]
        liquidations_for_collateral_type = self.filter_safe_nodes_by_collateral_type(parsed_data['allRawLiquidations']['nodes'])
        recent_liquidations = [item['rawSafeBySafeId']['identifier'] for item in liquidations_for_collateral_type]
        transfers_for_collateral_type = self.filter_nodes_by_collateral_type(parsed_data['allSafeEngineTransfers']['nodes'])
        recent_transfers = [item['src'] for item in transfers_for_collateral_type] + [item['dst'] for item in transfers_for_collateral_type]
        #assert isinstance(recent_mods, list)
        #assert isinstance(recent_liquidations, list)
        #assert isinstance(recent_transfers, list)
        recent_changes = set(recent_mods + recent_liquidations + recent_transfers)
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
        return list(filter(lambda item: item['rawSafeBySafeId']['rawCollateralTypeByCollateralTypeId']['identifier'] == self.collateral_type.name, nodes))

    def filter_nodes_by_collateral_type(self, nodes: list):
        assert isinstance(nodes, list)
        return list(filter(lambda item: item['rawCollateralTypeByCollateralTypeId']['identifier'] == self.collateral_type.name, nodes))

    def safe_from_vdb_node(self, node: dict) -> Safe:
        assert isinstance(node, dict)

        address = Address(node['safeIdentifier'])
        safe_collateral = Wad(int(node['safeCollateral']))
        safe_debt = Wad(int(node['safeDebt']))

        return Safe(address, self.collateral_type, safe_collateral, safe_debt)

    init_query = """query {
      allSafes {
        nodes {
          safeIdentifier
          collateralTypeIdentifier
          safeCollateral
          safeDebt
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
      allSafeEngineMods(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawSafeBySafeId {
            rawCollateralTypeByCollateralTypeId {
              identifier
            }
            identifier
          }
        }
      }
      allRawLiquidations(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawSafeBySafeId {
            rawCollateralTypeByCollateralTypeId {
              identifier
            }
            identifier
          }
        }
      }
      allSafeEngineTransfers(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
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
