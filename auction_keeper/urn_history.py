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
from typing import List, Optional
from web3 import Web3

from pymaker import Address
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

    def get_urns(self) -> List[Urn]:
        if not self.vulcanize_endpoint:
            return self.get_urns_from_past_frobs()
        else:
            return self.get_urns_from_vulcanize()

    def get_urns_from_past_frobs(self) -> List[Urn]:
        urn_addresses = set()
        past_blocks = self.web3.eth.blockNumber - self.from_block
        frobs = self.mcd.vat.past_frobs(past_blocks, self.ilk)
        for frob in frobs:
            urn_addresses.add(frob.urn)

        urns = []
        for address in urn_addresses:
            urns.append(self.mcd.vat.urn(self.ilk, address))
        self.logger.debug(f"Found {len(urns)} urns among {len(frobs)} frobs in the past {past_blocks} blocks")
        return urns

    def get_urns_from_vulcanize(self) -> List[Urn]:
        raise NotImplementedError("Work in progress")
