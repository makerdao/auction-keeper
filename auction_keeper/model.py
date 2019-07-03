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

from pymaker.numeric import Ray

from auction_keeper.process import Process
from pymaker import Address
from pymaker.numeric import Wad, Ray, Rad


class Parameters:
    def __init__(self, flipper: Optional[Address], flapper: Optional[Address], flopper: Optional[Address], id: int):
        assert isinstance(flipper, Address) or (flipper is None)
        assert isinstance(flapper, Address) or (flapper is None)
        assert isinstance(flopper, Address) or (flopper is None)
        assert isinstance(id, int)

        self.flipper = flipper
        self.flapper = flapper
        self.flopper = flopper
        self.id = id

    def __eq__(self, other):
        assert isinstance(other, Parameters)

        return self.flipper == other.flipper and \
               self.flapper == other.flapper and \
               self.flopper == other.flopper and \
               self.id == other.id

    def __hash__(self):
        return hash((self.flipper, self.flapper, self.flopper, self.id))

    def __repr__(self):
        return pformat(vars(self))


class Status:
    def __init__(self,
                 id: int,
                 flipper: Optional[Address],
                 flapper: Optional[Address],
                 flopper: Optional[Address],
                 bid: Wad,
                 lot: Wad,
                 tab: Optional[Wad],
                 beg: Ray,
                 guy: Address,
                 era: int,
                 tic: int,
                 end: int,
                 price: Optional[Wad]):
        assert isinstance(id, int)
        assert isinstance(flipper, Address) or (flipper is None)
        assert isinstance(flapper, Address) or (flapper is None)
        assert isinstance(flopper, Address) or (flopper is None)
        # Numeric type of bid and lot depends on auction type; Dai values are bid in Rad, collateral and MKR in Wad.
        assert isinstance(bid, Wad) or isinstance(bid, Rad)
        assert isinstance(lot, Wad) or isinstance(lot, Rad)
        assert isinstance(tab, Rad) or (tab is None)
        assert isinstance(beg, Ray)
        assert isinstance(guy, Address)
        assert isinstance(era, int)
        assert isinstance(tic, int)
        assert isinstance(end, int)
        assert isinstance(price, Wad) or (price is None)

        self.id = id
        self.flipper = flipper
        self.flapper = flapper
        self.flopper = flopper
        self.bid = bid
        self.lot = lot
        self.tab = tab
        self.beg = beg
        self.guy = guy
        self.era = era
        self.tic = tic
        self.end = end
        self.price = price

    def __eq__(self, other):
        assert isinstance(other, Status)

        return self.id == other.id and \
               self.flipper == other.flipper and \
               self.flapper == other.flapper and \
               self.flopper == other.flopper and \
               self.bid == other.bid and \
               self.lot == other.lot and \
               self.tab == other.tab and \
               self.beg == other.beg and \
               self.guy == other.guy and \
               self.era == other.era and \
               self.tic == other.tic and \
               self.end == other.end and \
               self.price == other.price

    def __hash__(self):
        return hash((self.id,
                     self.flipper,
                     self.flapper,
                     self.flopper,
                     self.bid,
                     self.lot,
                     self.tab,
                     self.beg,
                     self.guy,
                     self.era,
                     self.tic,
                     self.end,
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
        self._arguments += f" --flipper {parameters.flipper}" if parameters.flipper is not None else ""
        self._arguments += f" --flapper {parameters.flapper}" if parameters.flapper is not None else ""
        self._arguments += f" --flopper {parameters.flopper}" if parameters.flopper is not None else ""
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
            "lot": str(input.lot),
            "beg": str(input.beg),
            "guy": str(input.guy),
            "era": int(input.era),
            "tic": int(input.tic),
            "end": int(input.end),
            "price": str(input.price) if input.price is not None else None,
        }

        if input.tab:
            record['tab'] = str(input.tab)

        if input.flipper:
            record['flipper'] = str(input.flipper)

        if input.flapper:
            record['flapper'] = str(input.flapper)

        if input.flopper:
            record['flopper'] = str(input.flopper)

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
