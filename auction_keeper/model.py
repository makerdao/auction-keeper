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

from threading import RLock

from pymaker import Wad, Address


class OutputMessage:
    def __init__(self, bid: Wad, lot: Wad, guy: Address, tic: int, end: int, price: Wad):
        assert(isinstance(bid, Wad))
        assert(isinstance(lot, Wad))
        assert(isinstance(guy, Address))
        assert(isinstance(tic, int))
        assert(isinstance(end, int))
        assert(isinstance(price, Wad))

        self.bid = bid
        self.lot = lot
        self.guy = guy
        self.tic = tic
        self.end = end
        self.price = price

    def __eq__(self, other):
        assert(isinstance(other, OutputMessage))




class InputMessage:
    def __init__(self, price: Wad, gas_price: Wad):
        assert(isinstance(price, Wad))
        assert(isinstance(gas_price, Wad))

        self.price = price
        self.gas_price = gas_price


class Auction:
    def __init__(self, price: Wad, gas_price: int):
        self.output = None
        self.output_lock = RLock()
        self.model = None
        self.transaction = None
        self.transaction_price = None

        #TODO these two will ultimately go away
        self.price = price
        self.gas_price = gas_price

        #TODO we will implement locking later
        self.lock = RLock()

    def x(self):
        pass

    def update_output(self, output: OutputMessage):
        assert(isinstance(output, OutputMessage))

        with self.output_lock:
            self.output = output
        print(self.output)

    def get_input(self):
        pass

        #TODO 1) first fetch the most recent from model, if there is any
        #           and save to self.input
        #TODO 2) return self.input

    def remove(self):
        self.model.stop()
