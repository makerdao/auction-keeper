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

from pymaker.deployment import DssDeployment
from pymaker.dss import Urn, Collateral

from auction_keeper.main import AuctionKeeper
from pymaker import Address
from pymaker.numeric import Wad
from tests.helper import args, wait_for_other_threads


# @pytest.fixture(scope="session")
# def d(web3, mcd, our_address, keeper_address, gal_address):
#     mcd = DssDeployment.deploy(web3=web3, debt_ceiling=Wad.from_number(100000000))
#     c = mcd.collaterals[0]
#     assert d.pit.file_line(c.ilk, Wad.from_number(100000000)).transact()  # Set collateral debt ceiling
#     assert d.cat.file_lump(c.ilk, Wad.from_number(100)).transact()  # Set liquidation Quantity of c at 100
#
#     # mint gem for cdp frob() by gal_address and our_address to draw dai
#     assert c.gem.mint(Wad.from_number(2000000)).transact()
#     assert c.gem.transfer(gal_address, Wad.from_number(1000000)).transact()
#
#     # Require to join the adapter
#     assert c.gem.approve(c.adapter.address).transact()
#     assert c.gem.approve(c.adapter.address).transact(from_address=gal_address)
#
#     # draw dai for our_address
#     assert c.adapter.join(Urn(our_address), Wad.from_number(1000000)).transact()
#     assert d.pit.frob(c.ilk, Wad.from_number(1000000), Wad.from_number(1000000)).transact()
#     assert d.dai_move.move(our_address, keeper_address, Wad.from_number(10000)).transact()
#
#     # mint MKR for the keeper
#     assert d.mkr.mint(Wad.from_number(100)).transact()
#     assert d.mkr.transfer(keeper_address, Wad.from_number(100)).transact()
#
#     return d

@pytest.fixture()
def flap_keeper(web3, c: Collateral, keeper_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flapper {mcd.flap.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--vow {mcd.vow.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def flop_keeper(web3, c: Collateral, keeper_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flopper {mcd.flop.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--vow {mcd.vow.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.mark.skip(reason="Needs updating to accommodate DSS changes")
class TestAuctionKeeperVow:
    def test_flap(self, our_address, flap_keeper, mcd):
        # given
        joy = mcd.vow.joy()
        awe = mcd.vow.awe()
        hump = mcd.vow.hump()
        bump = mcd.vow.bump()
        needed_joy = Wad.from_number(10) - joy + awe + hump + bump
        if needed_joy > Wad(0):
            assert mcd.dai_move.move(our_address, mcd.vow.address, needed_joy).transact(from_address=our_address)
        kicks = mcd.flap.kicks()

        # when
        flap_keeper.check_flap()

        # then
        assert mcd.flap.kicks() == kicks + 1

    def test_flop(self, flop_keeper, kick, mcd):
        print(mcd)
        # given
        kicks = mcd.flop.kicks()

        # when
        flop_keeper.check_flop()

        # then
        assert mcd.flop.kicks() == kicks + 1
