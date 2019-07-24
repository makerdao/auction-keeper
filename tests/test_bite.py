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

from auction_keeper.main import AuctionKeeper
from pymaker.numeric import Wad, Ray, Rad

from tests.conftest import create_unsafe_cdp
from tests.helper import args, time_travel_by, TransactionIgnoringTest, wait_for_other_threads


class TestAuctionKeeperBite(TransactionIgnoringTest):
    def test_bite_and_flip(self, web3, mcd, gal_address, keeper_address):
        # given
        c = mcd.collaterals[0]
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--flipper {c.flipper.address} "
                                         f"--cat {mcd.cat.address} "
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

        # cleanup
        time_travel_by(web3, c.flipper.tau() + 1)
