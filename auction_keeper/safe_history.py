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
from collections import namedtuple
from datetime import datetime, timedelta
from typing import Dict, Optional
from web3 import Web3

from pyflex import Address, Wad
from pyflex.deployment import GfDeployment
from pyflex.gf import CollateralType, SAFE

from gql import gql, Client, AIOHTTPTransport

class SAFEHistory:
    logger = logging.getLogger()
    cache_lookback = 12  # for handling block reorgs

    def __init__(self, web3: Web3, geb: GfDeployment, collateral_type: CollateralType, from_block: Optional[int],
                 graph_endpoint: Optional[str], graph_key: Optional[str]):
        assert isinstance(web3, Web3)
        assert isinstance(geb, GfDeployment)
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(from_block, int) or from_block is None
        assert isinstance(graph_endpoint, str) or graph_endpoint is None
        assert isinstance(graph_key, str) or graph_key is None
        assert from_block or graph_endpoint

        self.web3 = web3
        self.geb = geb
        self.collateral_type = collateral_type
        self.from_block = from_block
        self.graph_endpoint = graph_endpoint
        self.graph_key = graph_key
        self.cache_block = from_block
        self.cache = {}

    def get_safes(self) -> Dict[Address, SAFE]:
        """Returns a list of safes indexed by address"""
        return self._get_safes(use_graph=self.graph_endpoint is not None)

    def _get_safes(self, use_graph: bool = True) -> Dict[Address, SAFE]:
        start = datetime.now()
        safe_addresses = set()

        # Get a unique list of safe addresses
        from_block = max(0, self.cache_block - self.cache_lookback)
        to_block = self.web3.eth.blockNumber
        if use_graph:
            mods = self.get_past_safe_mods_from_graph(from_block=from_block,
                                                      to_block=to_block,
                                                      collateral_type=self.collateral_type)
            self.logger.debug(f"Retrieved {len(mods)} past safe mods from graph")
        else:
            mods = self.geb.safe_engine.past_safe_modifications(from_block=from_block,
                                                                to_block=to_block,
                                                                collateral_type=self.collateral_type)
            self.logger.debug(f"Retrieved {len(mods)} past safe mods from node")

        for mod in mods:
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

    def get_past_safe_mods_from_graph(self, from_block:int, to_block: int, collateral_type: CollateralType = None):
        Mod = namedtuple("Mod", "safe")
        current_block = self.web3.eth.blockNumber
        assert isinstance(from_block, int)
        assert from_block < current_block
        if to_block is None:
            to_block = current_block
        else:
            assert isinstance(to_block, int)
            assert to_block >= from_block
            assert to_block <= current_block
        assert isinstance(collateral_type, CollateralType) or collateral_type is None

        if self.graph_key:
            transport = AIOHTTPTransport(url=self.graph_endpoint, headers={'Authorization': self.graph_key})
        else:
            transport = AIOHTTPTransport(url=self.graph_endpoint)

        client = Client(transport=transport, fetch_schema_from_transport=True)

        query = gql(
        f"""
        query{{
            modifySAFECollateralizations(where: {{createdAtBlock_gte: {from_block}}}) {{
                safeHandler,
                collateralType {{
                    id
                }}

            }}
        }}
        """
        )
        result = client.execute(query)
        return [Mod(Address(safe['safeHandler'])) for safe in result['modifySAFECollateralizations'] \
                if safe['collateralType']['id'] == collateral_type.name]
