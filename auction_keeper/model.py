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
from pymaker import Address
from pymaker.auctions import AuctionContract, Clipper, Flipper, Flapper, Flopper
from pymaker.numeric import Wad, Ray, Rad


class Parameters:
    def __init__(self, auction_contract: AuctionContract, id: int):
        assert isinstance(auction_contract, AuctionContract)
        assert isinstance(id, int)

        self.auction_contract = auction_contract
        self.id = id

    def __eq__(self, other):
        assert isinstance(other, Parameters)
        return self.auction_contract == other.auction_contract and self.id == other.id

    def __hash__(self):
        return hash((self.auction_contract.address, self.id))

    def __repr__(self):
        return pformat(vars(self))


class Status:
    def __init__(self,
                 id: int,
                 clipper: Optional[Address],
                 flipper: Optional[Address],
                 flapper: Optional[Address],
                 flopper: Optional[Address],
                 bid: Wad,
                 lot: Wad,
                 tab: Optional[Wad],
                 beg: Optional[Wad],
                 guy: Address,
                 era: int,
                 tic: int,
                 end: int,
                 price: Optional[Wad]):
        assert isinstance(id, int)
        assert isinstance(clipper, Address) or (clipper is None)
        assert isinstance(flipper, Address) or (flipper is None)
        assert isinstance(flapper, Address) or (flapper is None)
        assert isinstance(flopper, Address) or (flopper is None)
        # Numeric type of bid and lot depends on auction type; Dai values are bid in Rad, collateral and MKR in Wad.
        assert isinstance(bid, Wad) or isinstance(bid, Rad)
        assert isinstance(lot, Wad) or isinstance(lot, Rad)
        assert isinstance(tab, Rad) or (tab is None)
        assert isinstance(beg, Wad) or (beg is None)
        assert isinstance(guy, Address)
        assert isinstance(era, int)
        assert isinstance(tic, int)
        assert isinstance(end, int)
        assert isinstance(price, Wad) or (price is None)

        self.id = id
        self.clipper = clipper
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
               self.clipper == other.clipper and \
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
                     self.clipper,
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

        if isinstance(parameters.auction_contract, Clipper):
            self._arguments += f" --clipper {parameters.auction_contract.address}"
        elif isinstance(parameters.auction_contract, Flipper):
            self._arguments += f" --flipper {parameters.auction_contract.address}"
        elif isinstance(parameters.auction_contract, Flapper):
            self._arguments += f" --flapper {parameters.auction_contract.address}"
        elif isinstance(parameters.auction_contract, Flopper):
            self._arguments += f" --flopper {parameters.auction_contract.address}"

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
            "guy": str(input.guy),
            "era": int(input.era),
            "tic": int(input.tic),
            "end": int(input.end),
            "price": str(input.price) if input.price is not None else None,
        }

        if input.tab:
            record['tab'] = str(input.tab)

        if input.beg:
            record['beg'] = str(input.beg)

        if input.clipper:
            record['clipper'] = str(input.clipper)
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
