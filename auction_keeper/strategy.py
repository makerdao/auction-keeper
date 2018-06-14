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

from typing import Optional

from auction_keeper.model import ModelInput
from pymaker import Transact, Wad
from pymaker.approval import directly
from pymaker.auctions import Flopper, Flapper, Flipper


class Strategy:
    def get_input(self, id: int):
        raise NotImplementedError


class FlipperStrategy(Strategy):
    def __init__(self, flipper: Flipper):
        assert(isinstance(flipper, Flipper))

        self.flipper = flipper

    def approve(self):
        # `Flipper` does not require any approval as collateral and Dai transfers happen directly in Vat
        pass

    def kicks(self) -> int:
        return self.flipper.kicks()

    def get_input(self, id: int) -> ModelInput:
        assert(isinstance(id, int))

        # Read auction state
        bid = self.flipper.bids(id)

        # Prepare the model input from auction state
        return ModelInput(bid=bid.bid,
                          lot=bid.lot,
                          beg=self.flipper.beg(),
                          guy=bid.guy,
                          era=self.flipper.era(),
                          tic=bid.tic,
                          end=bid.end,
                          price=(bid.bid / bid.lot) if bid.lot != Wad(0) else Wad(0))

    def bid(self, id: int, price: Wad) -> Optional[Transact]:
        assert(isinstance(id, int))
        assert(isinstance(price, Wad))

        bid = self.flipper.bids(id)

        # Check if we can bid.
        # If we can, bid.
        auction_price = bid.bid / bid.lot
        auction_price_min_decrement = auction_price * self.flipper.beg()

        if price <= auction_price_min_decrement:
            pass
            our_lot = bid.bid / price #TODO TODO TODO
            # our_bid = bid.lot / price

            # TODO this should happen asynchronously
            # return self.flipper.tend(id, bid.lot, our_bid)

        else:
            return None

    def deal(self, id: int) -> Transact:
        return self.flipper.deal(id)


class FlapperStrategy(Strategy):
    def __init__(self, flapper: Flapper):
        assert(isinstance(flapper, Flapper))

        self.flapper = flapper

    def approve(self):
        self.flapper.approve(directly())

    def kicks(self) -> int:
        return self.flapper.kicks()

    def get_input(self, id: int) -> ModelInput:
        assert(isinstance(id, int))

        # Read auction state
        bid = self.flapper.bids(id)

        # Prepare the model input from auction state
        return ModelInput(bid=bid.bid,
                          lot=bid.lot,
                          beg=self.flapper.beg(),
                          guy=bid.guy,
                          era=self.flapper.era(),
                          tic=bid.tic,
                          end=bid.end,
                          price=(bid.lot / bid.bid) if bid.bid != Wad(0) else Wad(0))

    def bid(self, id: int, price: Wad) -> Optional[Transact]:
        assert(isinstance(id, int))
        assert(isinstance(price, Wad))

        bid = self.flapper.bids(id)

        # Check if we can bid.
        # If we can, bid.
        auction_price = bid.lot / bid.bid
        auction_price_min_decrement = auction_price * self.flapper.beg()

        if price <= auction_price_min_decrement:
            our_bid = bid.lot / price

            # TODO this should happen asynchronously
            return self.flapper.tend(id, bid.lot, our_bid)

        else:
            return None

    def deal(self, id: int) -> Transact:
        return self.flapper.deal(id)


class FlopperStrategy(Strategy):
    def __init__(self, flopper: Flopper):
        assert(isinstance(flopper, Flopper))

        self.flopper = flopper

    def approve(self):
        self.flopper.approve(directly())

    def kicks(self) -> int:
        return self.flopper.kicks()

    def get_input(self, id: int) -> ModelInput:
        assert(isinstance(id, int))

        # Read auction state
        bid = self.flopper.bids(id)

        # Prepare the model input from auction state
        return ModelInput(bid=bid.bid,
                          lot=bid.lot,
                          beg=self.flopper.beg(),
                          guy=bid.guy,
                          era=self.flopper.era(),
                          tic=bid.tic,
                          end=bid.end,
                          price=(bid.bid / bid.lot) if bid.lot != Wad(0) else Wad(0))

    def bid(self, id: int, price: Wad) -> Optional[Transact]:
        assert(isinstance(id, int))
        assert(isinstance(price, Wad))

        bid = self.flopper.bids(id)

        # Check if we can bid.
        # If we can, bid.
        auction_price = bid.bid / bid.lot
        auction_price_min_increment = auction_price * self.flopper.beg()

        if price >= auction_price_min_increment:
            our_lot = bid.bid / price

            # TODO this should happen asynchronously
            return self.flopper.dent(id, our_lot, bid.bid)

        else:
            return None

    def deal(self, id: int) -> Transact:
        return self.flopper.deal(id)
