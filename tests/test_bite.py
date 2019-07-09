# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 bargst
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
from pymaker.dss import Urn, Collateral
from pymaker.numeric import Wad, Ray, Rad

from tests.conftest import create_unsafe_cdp, create_keeper
from tests.helper import TransactionIgnoringTest, wait_for_other_threads


class TestAuctionKeeperBite(TransactionIgnoringTest):
    def test_bite_and_flip(self, mcd, gal_address):
        # given
        c = mcd.collaterals[0]
        keeper = create_keeper(mcd, c)
        unsafe_cdp = create_unsafe_cdp(mcd, c, Wad.from_number(1.2), gal_address)
        assert len(mcd.active_auctions()["flips"][c.ilk.name]) == 0

        # when
        keeper.check_cdps()
        wait_for_other_threads()

        # then
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been biten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert c.flipper.kicks() == 1  # One auction started
