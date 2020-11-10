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
from datetime import datetime
from typing import Dict

from pymaker import Address, Wad
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn
from auction_keeper.urn_history import UrnHistoryProvider

logger = logging.getLogger()


class TokenFlowUrnHistoryProvider(UrnHistoryProvider):
    def __init__(self, mcd: DssDeployment, ilk: Ilk, tokenflow_endpoint: str):
        assert isinstance(tokenflow_endpoint, str)
        super().__init__(ilk)
        self.mcd = mcd
        self.tokenflow_endpoint = tokenflow_endpoint + "/api"

    def get_urns(self) -> Dict[Address, Urn]:
        response = requests.get(self.tokenflow_endpoint + f"/vaults_list?ilk[in]={self.ilk.name}", timeout=30)
        if not response.ok:
            error_msg = f"{response.status_code} {response.reason} ({response.text})"
            raise RuntimeError(f"TokenFlow query failed: {error_msg}")
        data = response.json()['Message']['vaults']
        for item in data:
            urn = self.urn_from_tokenflow_item(item)
            self.cache[urn.address] = urn
        return self.cache

    def urn_from_tokenflow_item(self, item: dict) -> Urn:
        assert isinstance(item, dict)

        address = Address(item['owner'])
        ink = Wad(int(item['collateral']))
        art = Wad(int(item['debt']))

        return Urn(address, self.ilk, ink, art)
