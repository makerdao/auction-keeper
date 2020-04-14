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
from pymaker.gas import GasPrice, GeometricGasPrice


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
        self.initial_multiplier = arguments.gas_initial_multiplier
        self.reactive_multiplier = arguments.gas_reactive_multiplier
        self.gas_maximum = arguments.gas_maximum

    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        # start with fast price
        fast_price = self.gas_station.fast_price() if self.gas_station else None

        # if API produces no price, or remote feed not configured, use the default strategy
        if fast_price is None:
            return self.default_gas_pricing(time_elapsed)
        # start with the fast price times an initial multiplier which tunes aggressiveness
        elif time_elapsed < 30:
            return fast_price * self.initial_multiplier
        # if we get here often; the initial multiplier is insufficiently aggressive
        # TODO: Consider logging a warning that TX hasn't been mined after 30sec.
        else:
            # CAUTION: Since this is stateless, fast_price may have dropped, which means the reactive multiplier
            # cannot guarantee a replacement will occur.
            return GeometricGasPrice(initial_price=fast_price,
                                     every_secs=30,
                                     coefficient=self.reactive_multiplier,
                                     max_price=self.gas_maximum * self.GWEI).get_gas_price(time_elapsed)

    # default gas pricing when remote feed is down or not configured
    def default_gas_pricing(self, time_elapsed: int):
        return GeometricGasPrice(initial_price=10*self.GWEI,
                                 every_secs=30,
                                 coefficient=self.reactive_multiplier,
                                 max_price=self.gas_maximum*self.GWEI).get_gas_price(time_elapsed)
