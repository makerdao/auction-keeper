# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019-2021 EdNoepel
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

        self.cache_block = self.get_cached_block()

        urns_for_ilk = self.get_urns_by_ilk(self.ilk.name)
        for item in urns_for_ilk:
            try:
                urn = self.urn_from_vdb_node(item)
                self.cache[urn.address] = urn
            except TypeError as ex:
                logger.warning(f"Urn data {item} could not be processed: {ex}")
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

    def get_cached_block(self):
        response = self.run_query(self.lag_query)
        data = json.loads(response.text)['data']

        if data['untransformed']['totalCount'] > 0:
            # TODO: check this implementation once untransformed diffs exist
            return min(map(lambda n: int(n), data['untransformed']['nodes']))
        else:
            return int(data['lastBlock']['nodes'][0]['blockNumber'])

    def get_urns_by_ilk(self, ilk: str):
        assert isinstance(ilk, str)
        nodes = []
        data_needed = True
        page_size = 10000
        offset = 0
        while data_needed:
            urn_response = self.run_query(query=self.init_query, variables={'ilk': ilk, 'offset': offset})
            result = json.loads(urn_response.text)
            node_count = len(result['data']['getUrnsByIlk']['nodes'])
            logging.debug(f"Found {node_count} {ilk} urns from Vulcanize offset {offset}")
            if node_count > 0:  # There are more results to add
                nodes += result['data']['getUrnsByIlk']['nodes']
                offset += page_size
            else:  # No more results were returned, assume we read all the records
                data_needed = False

        return nodes

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

    init_query = """query ($ilk: String, $offset: Int) {
      getUrnsByIlk(ilkIdentifier: $ilk, first:10000, offset: $offset) {
        nodes {
          ilkIdentifier
          urnIdentifier
          ink
          art
        }
      }
    }"""

    lag_query = """query {
      untransformed: getBlockHeightsForNewUntransformedDiffs(first:50) {
        totalCount
        nodes
      }
      lastBlock: allHeaders(last: 1) {
        nodes {
          blockNumber
        }
      }
    }"""

    recent_changes_query = """query($fromBlock: BigInt) {
      allVatFrobs(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}}, first:10000)
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
      allRawBites(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}}, first:10000)
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
      allVatForks(filter: {headerByHeaderId: {blockNumber: {greaterThan: $fromBlock}}}, first:10000)
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
