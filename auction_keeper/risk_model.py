# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus
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

from pymaker import Wad, Address


class ModelParameters:
    def __init__(self, id: int):
        assert(isinstance(id, int))

        self.id = id

    def __eq__(self, other):
        assert(isinstance(other, ModelParameters))

        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return pformat(vars(self))


class ModelInput:
    def __init__(self, bid: Wad, lot: Wad, guy: Address, era: int, tic: int, end: int, price: Wad):
        assert(isinstance(bid, Wad))
        assert(isinstance(lot, Wad))
        assert(isinstance(guy, Address))
        assert(isinstance(era, int))
        assert(isinstance(tic, int))
        assert(isinstance(end, int))
        assert(isinstance(price, Wad))

        self.bid = bid
        self.lot = lot
        self.guy = guy
        self.era = era
        self.tic = tic
        self.end = end
        self.price = price

    def __eq__(self, other):
        assert(isinstance(other, ModelInput))

        return self.bid == other.bid and \
               self.lot == other.lot and \
               self.guy == other.guy and \
               self.era == other.era and \
               self.tic == other.tic and \
               self.end == other.end and \
               self.price == other.price

    def __hash__(self):
        return hash((self.bid, self.lot, self.guy, self.era, self.tic, self.end, self.price))

    def __repr__(self):
        return pformat(vars(self))


class ModelOutput:
    def __init__(self, price: Wad, gas_price: Wad):
        assert(isinstance(price, Wad))
        assert(isinstance(gas_price, Wad)) #TODO I think `gas_price` should be optional, then we should default to node default.

        self.price = price
        self.gas_price = gas_price

    def __eq__(self, other):
        assert(isinstance(other, ModelOutput))

        return self.price == other.price and \
               self.gas_price == other.gas_price

    def __hash__(self):
        return hash((self.price, self.gas_price))

    def __repr__(self):
        return pformat(vars(self))


class Model:
    def start(self, parameters: ModelParameters):
        raise NotImplementedError

    def input(self, input: ModelInput):
        raise NotImplementedError

    def output(self) -> Optional[ModelOutput]:
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class ModelFactory:
    def create_model(self) -> Model:
        raise NotImplementedError
