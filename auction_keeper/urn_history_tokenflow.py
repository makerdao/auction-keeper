# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 EdNoepel
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
from eth_utils import to_checksum_address
from typing import Dict
from web3 import Web3

from pymaker import Address, Wad
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn
from auction_keeper.urn_history import UrnHistoryProvider

logger = logging.getLogger()


class TokenFlowUrnHistoryProvider(UrnHistoryProvider):
    def __init__(self, web3: Web3, mcd: DssDeployment, ilk: Ilk, tokenflow_endpoint: str, chunk_size=20000):
        assert isinstance(tokenflow_endpoint, str)
        assert isinstance(chunk_size, int)
        super().__init__(ilk)
        self.web3 = web3
        self.mcd = mcd
        self.tokenflow_endpoint = tokenflow_endpoint + "/api"
        self.chunk_size = chunk_size

    def get_urns(self) -> Dict[Address, Urn]:
        # Determine what block TokenFlow data represents
        response = requests.get(self.tokenflow_endpoint + f"/last_block", timeout=30)
        if response.ok:
            last_block = response.json()['Message']['last_block']
        else:
            logger.error(f"Unable to determine last_block for TokenFlow data: {response.text}")
            last_block = self.web3.eth.blockNumber - 538  # 2 hours of history

        # Retrieve state from TokenFlow
        response = requests.get(self.tokenflow_endpoint + f"/vaults_list?ilk[in]={self.ilk.name}", timeout=30)
        if not response.ok:
            error_msg = f"{response.status_code} {response.reason} ({response.text})"
            raise RuntimeError(f"TokenFlow query failed: {error_msg}")
        data = response.json()['Message']['vaults']
        for item in data:
            urn = self.urn_from_tokenflow_item(item)
            self.cache[urn.address] = urn

        # Fill in data from recent blocks
        to_block = self.web3.eth.blockNumber
        if to_block > last_block:
            from_block = max(0, last_block - 10)  # reorg protection
            frobs = self.mcd.vat.past_frobs(from_block=from_block, to_block=to_block, ilk=self.ilk,
                                            chunk_size=self.chunk_size)
            recent_urns = set()
            for frob in frobs:
                recent_urns.add(frob.urn)
            for address in recent_urns:
                self.cache[address] = self.mcd.vat.urn(self.ilk, address)
            logger.debug(f"TokenFlow had data up to block {last_block}; loaded data for {len(recent_urns)} urns "
                         f"from chain up to block {to_block} (TokenFlow was {to_block-last_block} blocks behind)")

        return self.cache

    def urn_from_tokenflow_item(self, item: dict) -> Urn:
        assert isinstance(item, dict)

        address = Address(to_checksum_address(item['urn']))
        ink = max(Wad(0), Wad.from_number(float(item['collateral'])))
        art = Wad(item['art'])

        return Urn(address, self.ilk, ink, art)
