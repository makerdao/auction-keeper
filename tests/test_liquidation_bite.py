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

from tests.conftest import web3, mcd, \
    create_unsafe_cdp, get_collateral_price, keeper_address, liquidate_urn, purchase_dai, repay_urn, reserve_dai, \
    set_collateral_price
from tests.helper import args, time_travel_by, TransactionIgnoringTest, wait_for_other_threads


@pytest.mark.timeout(60)
class TestAuctionKeeperBite(TransactionIgnoringTest):
    @classmethod
    def setup_class(cls):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        cls.web3 = web3()
        cls.mcd = mcd(cls.web3)
        cls.c = cls.mcd.collaterals['ETH-A']
        cls.keeper_address = keeper_address(cls.web3)
        cls.keeper = AuctionKeeper(args=args(f"--eth-from {cls.keeper_address.address} "
                                     f"--type flip "
                                     f"--from-block 1 "
                                     f"--ilk {cls.c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=cls.mcd.web3)
        cls.keeper.approve()

        assert get_collateral_price(cls.c) == Wad.from_number(200)
        if not repay_urn(cls.mcd, cls.c, cls.keeper_address):
            liquidate_urn(cls.mcd, cls.c, cls.keeper_address, cls.keeper_address)

        # Keeper won't bid with a 0 Dai balance
        if cls.mcd.vat.dai(cls.keeper_address) == Rad(0):
            purchase_dai(Wad.from_number(20), cls.keeper_address)
        assert cls.mcd.dai_adapter.join(cls.keeper_address, Wad.from_number(20)).transact(
            from_address=cls.keeper_address)

    def test_bite_and_flip(self, mcd, gal_address):
        # setup
        repay_urn(mcd, self.c, gal_address)

        # given 21 Dai / (200 price * 1.5 mat) == 0.1575 vault size
        unsafe_cdp = create_unsafe_cdp(mcd, self.c, Wad.from_number(0.1575), gal_address, draw_dai=False)
        assert len(mcd.active_auctions()["flips"][self.c.ilk.name]) == 0
        kicks_before = self.c.flipper.kicks()

        # when
        self.keeper.check_vaults()
        wait_for_other_threads()

        # then
        print(mcd.cat.past_bites(10))
        assert len(mcd.cat.past_bites(10)) > 0
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been bitten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert self.c.flipper.kicks() == kicks_before + 1  # One auction started

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
        set_collateral_price(cls.mcd, cls.c, Wad.from_number(200.00))
        assert threading.active_count() == 1
