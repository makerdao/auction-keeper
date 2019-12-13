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

    def __init__(self, web3: Web3, mcd: DssDeployment, ilk: Ilk, from_block: Optional[int],
                 vulcanize_endpoint: Optional[str]):
        assert isinstance(web3, Web3)
        assert isinstance(mcd, DssDeployment)
        assert isinstance(ilk, Ilk)
        assert isinstance(from_block, int) or from_block is None
        assert isinstance(vulcanize_endpoint, str) or vulcanize_endpoint is None
        assert from_block or vulcanize_endpoint

        self.web3 = web3
        self.mcd = mcd
        self.ilk = ilk
        self.from_block = from_block
        self.vulcanize_endpoint = vulcanize_endpoint

    def get_urns(self) -> Dict[str, Urn]:
        """Returns a list of urns indexed by address"""
        if self.vulcanize_endpoint:
            return self.get_urns_from_vulcanize()
        else:
            return self.get_urns_from_past_frobs()

    def get_urns_from_past_frobs(self) -> Dict[str, Urn]:
        start = datetime.now()
        urn_addresses = set()
        past_blocks = self.web3.eth.blockNumber - self.from_block
        frobs = self.mcd.vat.past_frobs(past_blocks, self.ilk)
        for frob in frobs:
            urn_addresses.add(frob.urn)
        self.logger.debug(f"Retrieved {len(frobs)} frobs and detected {len(urn_addresses)} urn addresses in "
                          f"{(datetime.now()-start).seconds} seconds")

        start = datetime.now()
        urns = {}
        for address in urn_addresses:
            urns[address] = (self.mcd.vat.urn(self.ilk, address))
        self.logger.debug(f"Found {len(urns)} urns among {len(frobs)} frobs in the past {past_blocks} blocks in "
                          f"{(datetime.now()-start).seconds} seconds")
        return urns

    def get_urns_from_vulcanize(self) -> Dict[str, Urn]:
        response = requests.post(self.vulcanize_endpoint, json={'query': self.get_query()})
        if not response.ok:
            error_msg = f"{response.status_code} {response.reason} ({response.text})"
            raise RuntimeError(f"Vulcanize query failed: {error_msg}")

        urns = {}
        raw = json.loads(response.text)['data']['allRawUrns']['edges']
        for item in raw:
            urn = self.urn_from_node(item['node'])
            urns[urn.address] = urn
        self.logger.debug(f"Found {len(urns)} urns from VulcanizeDB")
        return urns

    def get_query(self):
        ilk_id = self.ilk_ids[self.ilk.name]
        return self.query.replace("ILK_ID", str(ilk_id))

    def urn_from_node(self, node: dict) -> Urn:
        assert isinstance(node, dict)

        address = Address(node['identifier'])
        ink = Wad(0)
        art = Wad(0)
        for frob in node['vatFrobsByUrnId']['nodes']:
            ink += Wad(int(frob['dink']))
            art += Wad(int(frob['dart']))
        for bite in node['bitesByUrnId']['nodes']:
            ink -= Wad(int(bite['ink']))
            art -= Wad(int(bite['art']))
        # FIXME: Need to adjust for `flux`es which occur on the urn.

        return Urn(address, self.ilk, ink, art)

    ilk_ids = {
        "ETH-A": 1,
        "BAT-A": 2
    }

    query = """query {
      allRawUrns(condition: {ilkId: ILK_ID}) {
        edges {
          node {
            vatFrobsByUrnId {
              nodes {
                dink
                dart
              }
            }
            identifier
            bitesByUrnId {
              nodes {
                art
                ink
              }
            }
          }
        }
      }
    }"""