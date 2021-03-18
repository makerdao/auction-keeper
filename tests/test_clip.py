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

import logging
import pytest
import time

from auction_keeper.gas import DynamicGasPrice
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from datetime import datetime
from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.auctions import Clipper
from pymaker.collateral import Collateral
from pymaker.deployment import DssDeployment
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import collateral_clip, create_unsafe_cdp, keeper_address, mcd, models, \
                           reserve_dai, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from typing import Optional


DEBUG = False


@pytest.fixture()
def kick(mcd, collateral_clip: Collateral, gal_address) -> int:
    # Ensure we start with a clean urn
    urn = mcd.vat.urn(collateral_clip.ilk, gal_address)
    assert urn.ink == Wad(0)
    assert urn.art == Wad(0)

    # Bark an unsafe vault and return the id
    unsafe_cdp = create_unsafe_cdp(mcd, collateral_clip, Wad.from_number(1.0), gal_address)
    mcd.dog.bark(collateral_clip.ilk, unsafe_cdp).transact()
    barks = mcd.dog.past_barks(1)
    assert len(barks) == 1
    return collateral_clip.clipper.kicks()


@pytest.mark.timeout(500)
class TestAuctionKeeperClipper(TransactionIgnoringTest):
    def setup_class(self):
        if DEBUG:
            time.sleep(8)
        self.web3 = web3()
        self.mcd = mcd(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.collateral = collateral_clip(self.mcd)
        assert self.collateral.clipper
        assert not self.collateral.flipper
        self.clipper = self.collateral.clipper
        # FIXME: Shouldn't need to set --min-auction 1 instead of 0
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                              f"--type clip "
                                              f"--from-block 1 "
                                              f"--ilk {self.collateral.ilk.name} "
                                              f"--model ./bogus-model.sh"), web3=self.mcd.web3)
        self.keeper.approve()

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        self.default_gas_price = self.keeper.gas_price.get_gas_price(0)

    def approve(self, address: Address):
        assert isinstance(address, Address)
        self.clipper.approve(self.clipper.vat.address, approval_function=hope_directly(from_address=address))
        self.collateral.approve(address)

    def take_with_dai(self, id: int, price: Ray, address: Address):
        assert isinstance(id, int)
        assert isinstance(price, Ray)
        assert isinstance(address, Address)

        logging.debug("reserving Dai")
        reserve_dai(self.mcd, self.collateral, address, Wad(price), extra_collateral=Wad.from_number(2))
        assert self.mcd.vat.dai(address) >= Rad(price)

        logging.debug(f"attempting to take clip {id} at {price}")
        assert id == 1
        lot = self.clipper.sales(id).lot
        assert lot > Wad(0)
        self.clipper.validate_take(id, lot, price, address)
        assert self.clipper.take(id, lot, price, address).transact(from_address=address)

    def take_below_price(self, id: int, our_price: Ray, address: Address):
        lot = self.clipper.sales(id).lot
        (done, auction_price) = self.clipper.status(id)
        while not done and lot > Wad(0):
            time_travel_by(self.web3, 1)
            lot = self.clipper.sales(id).lot
            (done, auction_price) = self.clipper.status(id)
            if auction_price < our_price:
                self.take_with_dai(id, our_price, address)
                break
        assert self.clipper.sales(id).lot == Wad(0)

    def test_keeper_config(self):
        assert self.keeper.arguments.type == 'clip'
        assert self.keeper.get_contract().address == self.clipper.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, kick, other_address):
        # setup
        self.approve(other_address)  # prepare for cleanup

        # given
        (model, model_factory) = models(self.keeper, kick)
        (done, price) = self.clipper.status(kick)

        # when
        self.keeper.check_all_auctions()
        if not DEBUG:
            wait_for_other_threads()
        initial_sale = self.clipper.sales(kick)
        # then
        model_factory.create_model.assert_called_once_with(Parameters(auction_contract=self.keeper.collateral.clipper, id=kick))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == kick
        assert status.clipper == self.clipper.address
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == Wad(price)
        assert status.lot == initial_sale.lot
        assert status.tab == initial_sale.tab
        assert status.beg is None
        assert status.era > 0
        assert time.time() - 5 < status.tic < time.time() + 5
        assert status.price == Wad(price)

        # cleanup
        self.take_below_price(kick, Ray.from_number(150), other_address)
