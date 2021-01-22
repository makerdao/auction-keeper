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
from pymaker.dss import Ilk, Urn, Vat

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
        logs = self.mcd.vat.past_logs(from_block=from_block, to_block=to_block, ilk=self.ilk,
                                      chunk_size=self.chunk_size)
        for log in logs:
            if isinstance(log, Vat.LogFrob):
                urn_addresses.add(log.urn)
            if isinstance(log, Vat.LogFork) or isinstance(log, Vat.LogMove):
                urn_addresses.add(log.dst)

        # Update state of already-cached urns
        for count, (address, urn) in enumerate(self.cache.items()):
            if count % 100 == 0:
                logger.debug(f"Updated state of {count} out of {len(self.cache)} urns")
            self.cache[address] = self.mcd.vat.urn(self.ilk, address)

        # Cache state of newly discovered urns
        for count, address in enumerate(urn_addresses):
            if count % 100 == 0:
                logger.debug(f"Updated state of {count} out of {len(urn_addresses)} newly found urns")
            if address not in self.cache:
                self.cache[address] = self.mcd.vat.urn(self.ilk, address)

        logger.debug(f"Updated {len(self.cache)} urns in {(datetime.now() - start).seconds} seconds")
        self.cache_block = to_block
        return self.cache
