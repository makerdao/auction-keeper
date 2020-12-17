# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019-2020 EdNoepel
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
from datetime import datetime
from typing import Dict

from pymaker import Address, Wad
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn
from auction_keeper.urn_history import UrnHistoryProvider

logger = logging.getLogger()


class VulcanizeUrnHistoryProvider(UrnHistoryProvider):
    def __init__(self, mcd: DssDeployment, ilk: Ilk, vulcanize_endpoint: str, vulcanize_key: str):
        assert isinstance(vulcanize_endpoint, str)
        assert isinstance(vulcanize_key, str)
        super().__init__(ilk)
        self.mcd = mcd
        self.vulcanize_endpoint = vulcanize_endpoint
        self.vulcanize_key = vulcanize_key
        self.cache_block = 0

    def get_urns(self) -> Dict[Address, Urn]:
        start = datetime.now()

        response = self.run_query(self.lag_query)
        self.cache_block = int(json.loads(response.text)['data']['lastStorageDiffProcessed']['nodes'][0]['blockHeight'])

        response = self.run_query(self.init_query)
        raw = json.loads(response.text)['data']['allUrns']['nodes']
        for item in raw:
            if item['ilkIdentifier'] == self.ilk.name:
                urn = self.urn_from_vdb_node(item)
                self.cache[urn.address] = urn
        logger.debug(f"Found {len(self.cache)} urns from VulcanizeDB up to block {self.cache_block} "
                     f"in {(datetime.now() - start).seconds} seconds")

        start = datetime.now()
        from_block = max(0, self.cache_block - self.cache_lookback)
        response = self.run_query(self.recent_changes_query, {"fromBlock": from_block})
        parsed_data = json.loads(response.text)['data']

        frobs_for_ilk = self.filter_urn_nodes_by_ilk(parsed_data['allVatFrobs']['nodes'])
        recent_frobs = [item['rawUrnByUrnId']['identifier'] for item in frobs_for_ilk]
        bites_for_ilk = self.filter_urn_nodes_by_ilk(parsed_data['allRawBites']['nodes'])
        recent_bites = [item['rawUrnByUrnId']['identifier'] for item in bites_for_ilk]
        forks_for_ilk = self.filter_nodes_by_ilk(parsed_data['allVatForks']['nodes'])
        recent_forks = [item['src'] for item in forks_for_ilk] + [item['dst'] for item in forks_for_ilk]
        assert isinstance(recent_frobs, list)
        assert isinstance(recent_bites, list)
        assert isinstance(recent_forks, list)
        recent_changes = set(recent_frobs + recent_bites + recent_forks)
        for urn in recent_changes:
            address = Address(urn)
            self.cache[address] = self.mcd.vat.urn(self.ilk, address)

        current_block = int(parsed_data['lastBlock']['nodes'][0]['blockNumber'])
        logger.debug(f"Updated {len(recent_changes)} urns from block {from_block} to {current_block} "
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

    def filter_urn_nodes_by_ilk(self, nodes: list):
        assert isinstance(nodes, list)
        return list(filter(lambda item: item['rawUrnByUrnId']['rawIlkByIlkId']['identifier'] == self.ilk.name, nodes))

    def filter_nodes_by_ilk(self, nodes: list):
        assert isinstance(nodes, list)
        return list(filter(lambda item: item['rawIlkByIlkId']['identifier'] == self.ilk.name, nodes))

    def urn_from_vdb_node(self, node: dict) -> Urn:
        assert isinstance(node, dict)

        address = Address(node['urnIdentifier'])
        ink = Wad(int(node['ink']))
        art = Wad(int(node['art']))

        return Urn(address, self.ilk, ink, art)

    init_query = """query {
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

    recent_changes_query = """query($fromBlock: BigInt) {
      allVatFrobs(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawUrnByUrnId {
            rawIlkByIlkId {
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
            rawIlkByIlkId {
              identifier
            }
            identifier
          }
        }
      }
      allVatForks(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}})
      {
        nodes {
          rawIlkByIlkId {
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
