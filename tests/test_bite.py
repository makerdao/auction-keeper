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

from auction_keeper.main import AuctionKeeper
from pymaker.approval import hope_directly
from pymaker.numeric import Wad, Ray, Rad

from tests.conftest import create_unsafe_cdp, keeper_address, mcd, reserve_dai, web3
from tests.helper import args, time_travel_by, TransactionIgnoringTest, wait_for_other_threads


@pytest.mark.timeout(60)
class TestAuctionKeeperBite(TransactionIgnoringTest):
    def test_bite_and_flip(self, web3, mcd, gal_address, keeper_address):
        # given
        c = mcd.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--network testnet "
                                         f"--ilk {c.ilk.name} "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        keeper.approve()
        unsafe_cdp = create_unsafe_cdp(mcd, c, Wad.from_number(1.2), gal_address)
        assert len(mcd.active_auctions()["flips"][c.ilk.name]) == 0

        # when
        keeper.check_cdps()
        wait_for_other_threads()

        # then
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been bitten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert c.flipper.kicks() == 1  # One auction started

    @classmethod
    def teardown_class(cls):
        cls.eliminate_queued_debt(web3(), mcd(web3()), keeper_address(web3()))

    @classmethod
    def eliminate_queued_debt(cls, web3, mcd, keeper_address):
        # given the existence of queued debt
        assert mcd.vat.sin(mcd.vow.address) > Rad(0)
        c = mcd.collaterals['ETH-A']
        kick = c.flipper.kicks()
        last_bite = mcd.cat.past_bite(1)[0]

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
