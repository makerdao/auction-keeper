# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 bargst, EdNoepel
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

import pytest
import threading

from auction_keeper.main import AuctionKeeper
from pymaker.approval import hope_directly
from pymaker.numeric import Wad, Ray, Rad

from tests.conftest import web3, mcd, create_unsafe_cdp, keeper_address, reserve_dai, purchase_dai
from tests.helper import args, time_travel_by, TransactionIgnoringTest, wait_for_other_threads


@pytest.mark.timeout(60)
class TestAuctionKeeperBite(TransactionIgnoringTest):
    def setup_class(self):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        self.web3 = web3()
        self.mcd = mcd(self.web3)
        self.c = self.mcd.collaterals['ETH-C']
        self.keeper_address = keeper_address(self.web3)
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                     f"--type flip "
                                     f"--from-block 1 "
                                     f"--ilk {self.c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=self.mcd.web3)
        self.keeper.approve()

        # Keeper won't bid with a 0 Dai balance
        purchase_dai(Wad.from_number(20), self.keeper_address)
        assert self.mcd.dai_adapter.join(self.keeper_address, Wad.from_number(20)).transact(
            from_address=self.keeper_address)

    def test_bite_and_flip(self, mcd, gal_address):
        # given 21 Dai / (200 price * 1.2 mat) == 0.0875 vault size
        unsafe_cdp = create_unsafe_cdp(mcd, self.c, Wad.from_number(0.0875), gal_address, draw_dai=False)
        assert len(mcd.active_auctions()["flips"][self.c.ilk.name]) == 0

        # when
        self.keeper.check_vaults()
        wait_for_other_threads()

        # then
        print(mcd.cat.past_bites(10))
        assert len(mcd.cat.past_bites(10)) > 0
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been bitten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert self.c.flipper.kicks() == 1  # One auction started

    def test_should_not_bite_dusty_urns(self, mcd, gal_address):
        # given a lot smaller than the dust limit
        urn = mcd.vat.urn(self.c.ilk, gal_address)
        assert urn.art < Wad(self.c.ilk.dust)
        kicks_before = self.c.flipper.kicks()

        # when a small unsafe urn is created
        assert not mcd.cat.can_bite(self.c.ilk, urn)

        # then ensure the keeper does not bite it
        self.keeper.check_vaults()
        wait_for_other_threads()
        kicks_after = self.c.flipper.kicks()
        assert kicks_before == kicks_after

    @classmethod
    def teardown_class(cls):
        w3 = web3()
        cls.eliminate_queued_debt(w3, mcd(w3), keeper_address(w3))
        assert threading.active_count() == 1

    @classmethod
    def eliminate_queued_debt(cls, web3, mcd, keeper_address):
        if mcd.vat.sin(mcd.vow.address) == Rad(0):
            return

        # given the existence of queued debt
        c = mcd.collaterals['ETH-C']
        kick = c.flipper.kicks()
        last_bite = mcd.cat.past_bites(10)[0]

        # when a bid covers the CDP debt
        auction = c.flipper.bids(kick)
        reserve_dai(mcd, c, keeper_address, Wad(auction.tab) + Wad(1))
        c.flipper.approve(c.flipper.vat(), approval_function=hope_directly(from_address=keeper_address))
        c.approve(keeper_address)
        assert c.flipper.tend(kick, auction.lot, auction.tab).transact(from_address=keeper_address)
        time_travel_by(web3, c.flipper.ttl() + 1)
        assert c.flipper.deal(kick).transact()

        # when a bid covers the vow debt
        assert mcd.vow.sin_of(last_bite.era(web3)) > Rad(0)
        assert mcd.vow.flog(last_bite.era(web3)).transact(from_address=keeper_address)
        assert mcd.vow.heal(mcd.vat.sin(mcd.vow.address)).transact()

        # then ensure queued debt has been auctioned off
        assert mcd.vat.sin(mcd.vow.address) == Rad(0)
