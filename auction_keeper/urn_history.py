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


import logging
from datetime import datetime
from typing import Dict, Optional
from web3 import Web3

from pymaker import Address
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn

logger = logging.getLogger()


class UrnHistoryProvider:
    cache_lookback = 10  # for handling block reorgs

    def __init__(self, ilk: Ilk):
        assert isinstance(ilk, Ilk)
        self.ilk = ilk
        self.cache = {}

    def get_urns(self) -> Dict[Address, Urn]:
        raise NotImplementedError("Please subclass this method")


class ChainUrnHistoryProvider(UrnHistoryProvider):
    def __init__(self, web3: Web3, mcd: DssDeployment, ilk: Ilk, from_block: int, chunk_size=20000):
        assert isinstance(from_block, int)
        assert isinstance(chunk_size, int)
        super().__init__(ilk)
        self.web3 = web3
        self.mcd = mcd
        self.cache_block = from_block
        self.chunk_size = chunk_size

    def get_urns(self) -> Dict[Address, Urn]:
        start = datetime.now()
        urn_addresses = set()

        # Get a unique list of urn addresses
        from_block = max(0, self.cache_block - self.cache_lookback)
        to_block = self.web3.eth.blockNumber
        frobs = self.mcd.vat.past_frobs(from_block=from_block, to_block=to_block, ilk=self.ilk,
                                        chunk_size=self.chunk_size)
        for frob in frobs:
            urn_addresses.add(frob.urn)

        # Update state of already-cached urns
        for address, urn in self.cache.items():
            self.cache[address] = self.mcd.vat.urn(self.ilk, address)

        # Cache state of newly discovered urns
        for address in urn_addresses:
            if address not in self.cache:
                self.cache[address] = self.mcd.vat.urn(self.ilk, address)

        logger.debug(f"Updated {len(self.cache)} urns in {(datetime.now() - start).seconds} seconds")
        self.cache_block = to_block
        return self.cache
