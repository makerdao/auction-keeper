# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2021 EdNoepel
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

from auction_keeper.gas import DynamicGasPrice
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from datetime import datetime
from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.auctions import Flipper
from pymaker.collateral import Collateral
from pymaker.deployment import DssDeployment
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import bite, collateral_clip, create_unsafe_cdp, flog_and_heal, keeper_address, mcd, models, \
                           reserve_dai, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from typing import Optional


@pytest.fixture()
def kick(mcd, collateral_clip: Collateral, gal_address) -> int:
    # Ensure we start with a clean urn
    urn = mcd.vat.urn(collateral_clip.ilk, gal_address)
    assert urn.ink == Wad(0)
    assert urn.art == Wad(0)

    # Bite gal CDP
    unsafe_cdp = create_unsafe_cdp(mcd, collateral_clip, Wad.from_number(1.0), gal_address)
    return bite(mcd, collateral_clip, unsafe_cdp)


@pytest.mark.timeout(500)
class TestAuctionKeeperClipper(TransactionIgnoringTest):
    def setup_class(self):
        self.web3 = web3()
        self.mcd = mcd(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.collateral = collateral_clip(self.mcd)
        assert self.collateral.clipper
        assert not self.collateral.flipper
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                              f"--type clip "
                                              f"--from-block 1 "
                                              f"--ilk {self.collateral.ilk.name} "
                                              f"--model ./bogus-model.sh"), web3=self.mcd.web3)
        self.keeper.approve()

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        self.default_gas_price = self.keeper.gas_price.get_gas_price(0)

    def test_keeper_config(self):
        assert self.keeper.arguments.type == 'clip'
        assert self.keeper.get_contract().address == self.collateral.clipper.address
