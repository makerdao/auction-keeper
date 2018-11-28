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

from pymaker.gas import GasPrice


class UpdatableGasPrice(GasPrice):
    def __init__(self, gas_price: Optional[int]):
        assert isinstance(gas_price, int) or (gas_price is None)

        self.gas_price = gas_price

    def update_gas_price(self, gas_price: Optional[int]):
        assert isinstance(gas_price, int) or (gas_price is None)

        self.gas_price = gas_price

    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        return self.gas_price
