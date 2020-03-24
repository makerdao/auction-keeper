# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus, bargst
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

from typing import Optional

from pygasprice_client import EthGasStation, EtherchainOrg, POANetwork
from pymaker.gas import GasPrice, IncreasingGasPrice


class UpdatableGasPrice(GasPrice):
    def __init__(self, gas_price: Optional[int]):
        assert isinstance(gas_price, int) or (gas_price is None)

        self.gas_price = gas_price

    def update_gas_price(self, gas_price: Optional[int]):
        assert isinstance(gas_price, int) or (gas_price is None)

        self.gas_price = gas_price

    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        return self.gas_price


class DynamicGasPrice(GasPrice):

    GWEI = 1000000000

    def __init__(self, arguments):
        self.gas_station = None
        if arguments.ethgasstation_api_key:
            self.gas_station = EthGasStation(refresh_interval=60, expiry=600, api_key=arguments.ethgasstation_api_key)
        elif arguments.etherchain_gas:
            self.gas_station = EtherchainOrg(refresh_interval=60, expiry=600)
        elif arguments.poanetwork_gas:
            self.gas_station = POANetwork(refresh_interval=60, expiry=600, alt_url=arguments.poanetwork_url)

    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        # start with standard price plus backup in case gas price API is down, then do fast
        if 0 <= time_elapsed <= 60:
            standard_price = self.gas_station.standard_price() if self.gas_station else None

            if standard_price is not None:
                return int(standard_price*1.1)
            else:
                return self.default_gas_pricing(time_elapsed)

        # move to fast after a minute
        else:
            fast_price = self.gas_station.fast_price() if self.gas_station else None

            if fast_price is not None:
                return int(fast_price*1.1)
            else:
                return self.default_gas_pricing(time_elapsed)

    # default gas pricing when EthGasStation feed is down
    def default_gas_pricing(self, time_elapsed: int):
        return IncreasingGasPrice(initial_price=5*self.GWEI,
                                  increase_by=10*self.GWEI,
                                  every_secs=60,
                                  max_price=100*self.GWEI).get_gas_price(time_elapsed)
