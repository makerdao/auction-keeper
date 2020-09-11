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

import logging
from pprint import pformat
from typing import Optional

from auction_keeper.process import Process
from pyflex import Address
from pyflex.numeric import Wad, Ray, Rad


class Parameters:
    def __init__(self, collateral_auction_house: Optional[Address], surplus_auction_house: Optional[Address],
                 debt_auction_house: Optional[Address], id: int):
        assert isinstance(collateral_auction_house, Address) or (collateral_auction_house is None)
        assert isinstance(surplus_auction_house, Address) or (surplus_auction_house is None)
        assert isinstance(debt_auction_house, Address) or (debt_auction_house is None)
        assert isinstance(id, int)

        self.collateral_auction_house = collateral_auction_house
        self.surplus_auction_house = surplus_auction_house
        self.debt_auction_house = debt_auction_house
        self.id = id

    def __eq__(self, other):
        assert isinstance(other, Parameters)

        return self.collateral_auction_house == other.collateral_auction_house and \
               self.surplus_auction_house == other.surplus_auction_house and \
               self.debt_auction_house == other.debt_auction_house and \
               self.id == other.id

    def __hash__(self):
        return hash((self.collateral_auction_house, self.surplus_auction_house, self.debt_auction_house, self.id))

    def __repr__(self):
        return pformat(vars(self))


class Status:
    def __init__(self,
                 id: int,
                 collateral_auction_house: Optional[Address],
                 surplus_auction_house: Optional[Address],
                 debt_auction_house: Optional[Address],
                 bid_amount: Wad,
                 amount_to_sell: Wad,
                 amount_to_raise: Optional[Wad],
                 bid_increase: Wad,
                 high_bidder: Address,
                 era: int,
                 bid_expiry: int,
                 auction_deadline: int,
                 price: Optional[Wad]):
        assert isinstance(id, int)
        assert isinstance(collateral_auction_house, Address) or (collateral_auction_house is None)
        assert isinstance(surplus_auction_house, Address) or (surplus_auction_house is None)
        assert isinstance(debt_auction_house, Address) or (debt_auction_house is None)
        # Numeric type of bid and amount_to_sell depends on auction type; Dai values are bid in Rad, collateral and MKR in Wad.
        assert isinstance(bid, Wad) or isinstance(bid, Rad)
        assert isinstance(amount_to_sell, Wad) or isinstance(amount_to_sell, Rad)
        assert isinstance(amount_to_raise, Rad) or (amount_to_raise is None)
        assert isinstance(bid_increase, Wad)
        assert isinstance(high_bidder, Address)
        assert isinstance(era, int)
        assert isinstance(bid_expiry, int)
        assert isinstance(auction_deadline, int)
        assert isinstance(price, Wad) or (price is None)

        self.id = id
        self.collateral_auction_house = collateral_auction_house
        self.surplus_auction_house = surplus_auction_house
        self.debt_auction_house = debt_auction_house
        self.bid = bid
        self.amount_to_sell = amount_to_sell
        self.amount_to_raise = amount_to_raise
        self.bid_increase = bid_increase
        self.high_bidder = high_bidder
        self.era = era
        self.bid_expiry = bid_expiry
        self.auction_deadline = auction_deadline
        self.price = price

    def __eq__(self, other):
        assert isinstance(other, Status)

        return self.id == other.id and \
               self.collateral_auction_house == other.collateral_auction_house and \
               self.surplus_auction_house == other.surplus_auction_house and \
               self.debt_auction_house == other.debt_auction_house and \
               self.bid == other.bid and \
               self.amount_to_sell == other.amount_to_sell and \
               self.amount_to_raise == other.amount_to_raise and \
               self.bid_increase == other.bid_increase and \
               self.high_bidder == other.high_bidder and \
               self.era == other.era and \
               self.bid_expiry == other.bid_expiry and \
               self.auction_deadline == other.auction_deadline and \
               self.price == other.price

    def __hash__(self):
        return hash((self.id,
                     self.collateral_auction_house,
                     self.surplus_auction_house,
                     self.debt_auction_house,
                     self.bid,
                     self.amount_to_sell,
                     self.amount_to_raise,
                     self.bid_increase,
                     self.high_bidder,
                     self.era,
                     self.bid_expiry,
                     self.auction_deadline,
                     self.price))

    def __repr__(self):
        return pformat(vars(self))


class Stance:
    def __init__(self, price: Wad, gas_price: Optional[int]):
        assert isinstance(price, Wad)
        assert isinstance(gas_price, int) or (gas_price is None)

        self.price = price
        self.gas_price = gas_price

    def __eq__(self, other):
        assert isinstance(other, Stance)

        return self.price == other.price and \
               self.gas_price == other.gas_price

    def __hash__(self):
        return hash((self.price, self.gas_price))

    def __repr__(self):
        return pformat(vars(self))


class Model:
    logger = logging.getLogger()

    def __init__(self, command: str, parameters: Parameters):
        assert isinstance(command, str)
        assert isinstance(parameters, Parameters)

        self._command = command
        self._arguments = f"--id {parameters.id}"
        self._arguments += f" --collateral_auction_house {parameters.collateral_auction_house}" if parameters.collateral_auction_house is not None else ""
        self._arguments += f" --surplus_auction_house {parameters.surplus_auction_house}" if parameters.surplus_auction_house is not None else ""
        self._arguments += f" --debt_auction_house {parameters.debt_auction_house}" if parameters.debt_auction_house is not None else ""
        self._last_output = None

        self.logger.info(f"Instantiated model using process '{self._command} {self._arguments}'")

        self._process = Process(f"{self._command} {self._arguments}")
        self._process.start()

    def _ensure_process_running(self):
        if not self._process.running:
            self.logger.warning(f"Process '{self._command} {self._arguments}' is down, restarting it")

            self._process.start()

    def send_status(self, input: Status):
        assert isinstance(input, Status)

        self._ensure_process_running()

        record = {
            "id": str(input.id),
            "bid": str(input.bid),
            "amount_to_sell": str(input.amount_to_sell),
            "bid_increase": str(input.bid_increase),
            "high_bidder": str(input.high_bidder),
            "era": int(input.era),
            "bid_expiry": int(input.bid_expiry),
            "auction_deadline": int(input.auction_deadline),
            "price": str(input.price) if input.price is not None else None,
        }

        if input.amount_to_raise:
            record['amount_to_raise'] = str(input.amount_to_raise)

        if input.collateral_auction_house:
            record['collateral_auction_house'] = str(input.collateral_auction_house)

        if input.surplus_auction_house:
            record['surplus_auction_house'] = str(input.surplus_auction_house)

        if input.debt_auction_house:
            record['debt_auction_house'] = str(input.debt_auction_house)

        self._process.write(record)

    def get_stance(self) -> Optional[Stance]:
        self._ensure_process_running()

        while True:
            data = self._process.read()

            if data is not None:
                self._last_output = Stance(price=Wad.from_number(data['price']),
                                           gas_price=int(data['gasPrice']) if 'gasPrice' in data else None)

            else:
                break

        return self._last_output

    def terminate(self):
        self.logger.info(f"Terminating model using process '{self._command} {self._arguments}'")

        self._process.stop()


class ModelFactory:
    def __init__(self, command: str):
        assert isinstance(command, str)

        self.command = command

    def create_model(self, parameters: Parameters) -> Model:
        return Model(self.command, parameters)
