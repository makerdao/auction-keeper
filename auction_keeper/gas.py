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

from pprint import pformat
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
        self.fixed_gas = None
        if arguments.ethgasstation_api_key:
            self.gas_station = EthGasStation(refresh_interval=60, expiry=600, api_key=arguments.ethgasstation_api_key)
        elif arguments.etherchain_gas:
            self.gas_station = EtherchainOrg(refresh_interval=60, expiry=600)
        elif arguments.poanetwork_gas:
            self.gas_station = POANetwork(refresh_interval=60, expiry=600, alt_url=arguments.poanetwork_url)
        elif arguments.fixed_gas_price:
            self.fixed_gas = int(round(arguments.fixed_gas_price * self.GWEI))
        self.initial_multiplier = arguments.gas_initial_multiplier
        self.reactive_multiplier = arguments.gas_reactive_multiplier
        self.gas_maximum = int(round(arguments.gas_maximum * self.GWEI))
        if self.fixed_gas:
            assert self.fixed_gas <= self.gas_maximum

    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        # start with fast price from the configured gas API
        fast_price = self.gas_station.fast_price() if self.gas_station else None

        # if API produces no price, or remote feed not configured, start with a fixed price
        if fast_price is None:
            initial_price = self.fixed_gas if self.fixed_gas else 10 * self.GWEI
        # otherwise, use the API's fast price, adjusted by a coefficient, as our starting point
        else:
            initial_price = int(round(fast_price * self.initial_multiplier))

        return GeometricGasPrice(initial_price=initial_price,
                                 every_secs=30,
                                 coefficient=self.reactive_multiplier,
                                 max_price=self.gas_maximum).get_gas_price(time_elapsed)

    def __str__(self):
        retval = ""
        if self.gas_station:
            retval = f"{type(self.gas_station)} fast gas price with initial multiplier {self.initial_multiplier} "
        elif self.fixed_gas:
            retval = f"Fixed gas price {round(self.fixed_gas / self.GWEI, 1)} Gwei "
        else:
            retval = f"Default gas 10 Gwei "

        retval += f"and will multiply by {self.reactive_multiplier} every 30s to a maximum of " \
                  f"{round(self.gas_maximum / self.GWEI, 1)} Gwei"
        return retval

    def __repr__(self):
        return f"DynamicGasPrice({pformat(vars(self))})"
