# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2021 reverendus, bargst, EdNoepel
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
from typing import Optional, Tuple
from web3 import Web3

from auction_keeper.model import Status
from pymaker import Address, Transact
from pymaker.approval import directly, hope_directly
from pymaker.auctions import AuctionContract, Clipper, Flapper, Flipper, Flopper
from pymaker.gas import GasPrice
from pymaker.numeric import Wad, Ray, Rad


def era(web3: Web3):
    return web3.eth.getBlock('latest')['timestamp']


class Strategy:
    logger = logging.getLogger()

    def __init__(self, contract: AuctionContract):
        assert isinstance(contract, AuctionContract)
        self.contract = contract

    def approve(self, gas_price: GasPrice):
        raise NotImplementedError

    def get_input(self, id: int):
        raise NotImplementedError

    def deal(self, id: int) -> Transact:
        return self.contract.deal(id)

    def tick(self, id: int) -> Transact:
        return self.contract.tick(id)


class ClipperStrategy(Strategy):
    def __init__(self, clipper: Clipper):
        assert isinstance(clipper, Clipper)

        self.clipper = clipper

    def approve(self, gas_price: GasPrice):
        assert isinstance(gas_price, GasPrice)
        self.clipper.approve(self.clipper.vat.address, hope_directly(gas_price=gas_price))

    def kicks(self) -> int:
        return self.clipper.kicks()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        # TODO: Get lot from clipper.status once added
        sale = self.clipper.sales(id)
        (done, price) = self.clipper.status(id)

        # Calculating end time based on abaci parameters is nontrivial and omitted from this implementation.

        # Prepare the model input from auction state
        return Status(id=id,
                      clipper=self.clipper.address,
                      flipper=None,
                      flapper=None,
                      flopper=None,
                      bid=price * Ray(sale.lot),    # Cost to take rest of auction at current price
                      lot=sale.lot,                 # Wad
                      tab=sale.tab,
                      beg=None,
                      guy=None,
                      era=era(self.clipper.web3),
                      tic=sale.tic,
                      end=None,
                      price=price)             # Current price of auction

    def bid(self, id: int, our_price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(our_price, Wad)

        # TODO: Get lot from clipper.status once added
        sale = self.clipper.sales(id)
        (done, auction_price) = self.clipper.status(id)

        # TODO: Calculate how much of the lot we can afford with Dai available, don't bid for more than that

        if Ray(our_price) >= auction_price:
            self.logger.debug(f"taking {sale.lot} from auction {id} at {our_price}")
            cost = Rad(sale.lot) * Rad(our_price)
            return Wad(our_price), self.clipper.take(id, Wad(sale.lot), Ray(our_price)), cost
        else:
            self.logger.debug(f"auction {id} price is {auction_price}; cannot take at {our_price}")
            return None, None, None

    def deal(self, id: int) -> Transact:
        raise RuntimeError("Clipper auctions cannot be dealt")

    def tick(self, id: int) -> Transact:
        return self.clipper.redo(id, None)


class FlipperStrategy(Strategy):
    def __init__(self, flipper: Flipper, min_lot: Wad):
        assert isinstance(flipper, Flipper)
        assert isinstance(min_lot, Wad)
        super().__init__(flipper)

        self.flipper = flipper
        self.beg = flipper.beg()
        self.min_lot = min_lot

    def approve(self, gas_price: GasPrice):
        assert isinstance(gas_price, GasPrice)
        self.flipper.approve(self.flipper.vat(), hope_directly(gas_price=gas_price))

    def kicks(self) -> int:
        return self.flipper.kicks()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.flipper.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      clipper=None,
                      flipper=self.flipper.address,
                      flapper=None,
                      flopper=None,
                      bid=bid.bid,  # Rad
                      lot=bid.lot,  # Wad
                      tab=bid.tab,
                      beg=self.beg,
                      guy=bid.guy,
                      era=era(self.flipper.web3),
                      tic=bid.tic,
                      end=bid.end,
                      price=Wad(bid.bid / Rad(bid.lot)) if bid.lot != Wad(0) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.flipper.bids(id)

        # dent phase
        if bid.bid == bid.tab:
            our_lot = Wad(bid.bid / Rad(price))
            if our_lot < self.min_lot:
                self.logger.debug(f"dent lot {our_lot} less than minimum {self.min_lot} for auction {id}")
                return None, None, None

            if (our_lot * self.beg <= bid.lot) and (our_lot < bid.lot):
                return price, self.flipper.dent(id, our_lot, bid.bid), bid.bid
            else:
                self.logger.debug(f"dent lot {our_lot} would not exceed the bid increment for auction {id}")
                return None, None, None

        # tend phase
        else:
            if bid.lot < self.min_lot:
                self.logger.debug(f"tend lot {bid.lot} less than minimum {self.min_lot} for auction {id}")
                return None, None, None

            our_bid = Rad.min(Rad(bid.lot) * price, bid.tab)
            our_price = price if our_bid < bid.tab else Wad(bid.bid) / bid.lot

            if (our_bid >= bid.bid * self.beg or our_bid == bid.tab) and our_bid > bid.bid:
                return our_price, self.flipper.tend(id, bid.lot, our_bid), Rad(our_bid)
            else:
                self.logger.debug(f"tend bid {our_bid} would not exceed the bid increment for auction {id}")
                return None, None, None


class FlapperStrategy(Strategy):
    def __init__(self, flapper: Flapper, mkr: Address):
        assert isinstance(flapper, Flapper)
        assert isinstance(mkr, Address)
        super().__init__(flapper)

        self.flapper = flapper
        self.beg = flapper.beg()
        self.mkr = mkr

    def approve(self, gas_price: GasPrice):
        self.flapper.approve(self.mkr, directly(gas_price=gas_price))

    def kicks(self) -> int:
        return self.flapper.kicks()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.flapper.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      clipper=None,
                      flipper=None,
                      flapper=self.flapper.address,
                      flopper=None,
                      bid=bid.bid,
                      lot=bid.lot,
                      tab=None,
                      beg=self.beg,
                      guy=bid.guy,
                      era=era(self.flapper.web3),
                      tic=bid.tic,
                      end=bid.end,
                      price=Wad(bid.lot / Rad(bid.bid)) if bid.bid > Wad.from_number(0.000001) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.flapper.bids(id)
        our_bid = bid.lot / Rad(price)

        if our_bid >= Rad(bid.bid) * Rad(self.beg) and our_bid > Rad(bid.bid):
            return price, self.flapper.tend(id, bid.lot, Wad(our_bid)), Rad(our_bid)
        else:
            self.logger.debug(f"bid {our_bid} would not exceed the bid increment for auction {id}")
            return None, None, None


class FlopperStrategy(Strategy):
    def __init__(self, flopper: Flopper):
        assert isinstance(flopper, Flopper)
        super().__init__(flopper)

        self.flopper = flopper
        self.beg = flopper.beg()

    def approve(self, gas_price: GasPrice):
        self.flopper.approve(self.flopper.vat(), hope_directly(gas_price=gas_price))

    def kicks(self) -> int:
        return self.flopper.kicks()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.flopper.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      clipper=None,
                      flipper=None,
                      flapper=None,
                      flopper=self.flopper.address,
                      bid=bid.bid,
                      lot=bid.lot,
                      tab=None,
                      beg=self.beg,
                      guy=bid.guy,
                      era=era(self.flopper.web3),
                      tic=bid.tic,
                      end=bid.end,
                      price=Wad(bid.bid / Rad(bid.lot)) if bid.lot != Wad(0) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.flopper.bids(id)
        our_lot = bid.bid / Rad(price)

        if Ray(our_lot) * self.beg <= Ray(bid.lot) and our_lot < Rad(bid.lot):
            return price, self.flopper.dent(id, Wad(our_lot), bid.bid), bid.bid
        else:
            self.logger.debug(f"lot {our_lot} would not exceed the bid increment for auction {id}")
            return None, None, None
