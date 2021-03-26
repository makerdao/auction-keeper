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
import threading
import time

from auction_keeper.gas import DynamicGasPrice
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.auctions import Clipper
from pymaker.collateral import Collateral
from pymaker.deployment import DssDeployment
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import collateral_clip, create_unsafe_cdp, flog_and_heal, gal_address, keeper_address, mcd, \
    models, other_address, reserve_dai, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


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


@pytest.mark.skip("testing file rename effects")
@pytest.mark.timeout(500)
class TestAuctionKeeperClipper(TransactionIgnoringTest):
    @classmethod
    def setup_class(cls):
        cls.web3 = web3()
        cls.mcd = mcd(cls.web3)
        cls.gal_address = gal_address(cls.web3)
        cls.keeper_address = keeper_address(cls.web3)
        cls.other_address = other_address(cls.web3)
        cls.collateral = collateral_clip(cls.mcd)
        assert cls.collateral.clipper
        assert not cls.collateral.flipper
        cls.clipper = cls.collateral.clipper
        # FIXME: Shouldn't need to set --min-auction 1 instead of 0
        cls.keeper = AuctionKeeper(args=args(f"--eth-from {cls.keeper_address.address} "
                                              f"--type clip "
                                              f"--from-block 1 "
                                              f"--ilk {cls.collateral.ilk.name} "
                                              f"--model ./bogus-model.sh"), web3=cls.mcd.web3)
        cls.keeper.approve()

        # approve another taker
        cls.collateral.approve(cls.other_address)
        cls.collateral.clipper.approve(cls.mcd.vat.address, hope_directly(from_address=cls.other_address))

        assert isinstance(cls.keeper.gas_price, DynamicGasPrice)
        cls.default_gas_price = cls.keeper.gas_price.get_gas_price(0)

    def approve(self, address: Address):
        assert isinstance(address, Address)
        self.clipper.approve(self.clipper.vat.address, approval_function=hope_directly(from_address=address))
        self.collateral.approve(address)

    def last_log(self):
        current_block = self.clipper.web3.eth.blockNumber
        return self.clipper.past_logs(current_block - 1, current_block)[0]

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

    def simulate_model_bid(self, model, price: Ray):
        assert isinstance(price, Ray)
        assert price > Ray(0)

        assert model.id > 0
        sale = self.clipper.sales(model.id)
        assert sale.lot > Wad(0)

        our_bid = Ray(sale.lot) * price
        reserve_dai(self.mcd, self.collateral, self.keeper_address, Wad(our_bid) + Wad(1), extra_collateral=Wad.from_number(2))
        simulate_model_output(model=model, price=Wad(price))

    def take_below_price(self, id: int, our_price: Ray, address: Address):
        assert isinstance(id, int)
        assert isinstance(our_price, Ray)
        assert isinstance(address, Address)

        (needs_redo, auction_price, lot, tab) = self.clipper.status(id)
        while lot > Wad(0):
            time_travel_by(self.web3, 1)
            (needs_redo, auction_price, lot, tab) = self.clipper.status(id)
            if auction_price < our_price:
                self.take_with_dai(id, our_price, address)
                break
        assert self.clipper.sales(id).lot == Wad(0)

    def test_keeper_config(self):
        assert self.keeper.arguments.type == 'clip'
        assert self.keeper.get_contract().address == self.clipper.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, kick):

        # given
        (model, model_factory) = models(self.keeper, kick)
        (needs_redo, price, lot, tab) = self.clipper.status(kick)

        # when
        self.keeper.check_all_auctions()
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
        assert status.bid == Ray(status.lot) * status.price
        assert status.lot == initial_sale.lot
        assert status.tab == initial_sale.tab
        assert status.beg is None
        assert status.era > 0
        assert time.time() - 5 < status.tic < time.time() + 5
        assert status.price == price

    def test_should_do_nothing_if_no_output_from_model(self, other_address):
        # setup
        self.approve(other_address)  # prepare for cleanup
        # given previous kick
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

        # cleanup
        kick = self.clipper.kicks()
        self.take_below_price(kick, Ray.from_number(150), other_address)

    def test_should_take_when_price_appropriate(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        our_price = Ray.from_number(153)
        self.simulate_model_bid(model, our_price)

        while True:
            time_travel_by(self.web3, 1)
            self.keeper.check_all_auctions()
            self.keeper.check_for_bids()
            wait_for_other_threads()
            lot = self.clipper.sales(kick).lot
            (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)

            # when auction price is unacceptable
            if auction_price > our_price:
                # then ensure no action is taken
                assert self.clipper.sales(kick).lot > Wad(0)
                assert not needs_redo
            # when auction price is acceptable
            else:
                # then ensure take was called
                assert self.clipper.sales(kick).lot == Wad(0)
                break

        # and ensure the take price was appropriate
        our_take = self.last_log()
        assert isinstance(our_take, Clipper.TakeLog)
        assert our_take.price <= our_price

    def test_should_take_after_someone_else_took(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        sale = self.clipper.sales(kick)
        assert sale.lot == Wad.from_number(1)

        # when another actor took most of the lot
        time_travel_by(self.web3, 12)
        sale = self.clipper.sales(kick)
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        their_amt = Wad.from_number(0.6)
        their_bid = Wad(Ray(their_amt) * price)
        assert Rad(their_bid) < sale.tab  # ensure some collateral will be left over
        reserve_dai(self.mcd, self.collateral, self.other_address, their_bid)
        self.clipper.validate_take(kick, their_amt, price, self.other_address)
        assert self.clipper.take(kick, their_amt, price, self.other_address).transact(from_address=self.other_address)
        sale = self.clipper.sales(kick)
        assert sale.lot > Wad(0)

        # and our model is configured to bid a few seconds into the auction
        sale = self.clipper.sales(kick)
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        assert Rad(price) > sale.tab
        self.simulate_model_bid(model, price)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()

        # then ensure we took the remaining lot
        our_take = self.last_log()
        assert isinstance(our_take, Clipper.TakeLog)
        assert Wad(0) < our_take.lot <= lot

    @staticmethod
    def print_imbalance(mcd: DssDeployment):
        awe = mcd.vat.sin(mcd.vow.address)
        woe = awe - mcd.vow.sin() - mcd.vow.ash()
        joy = mcd.vat.dai(mcd.vow.address)
        balance = joy - awe
        sump = mcd.vow.sump()
        print(f"balance={float(balance)}, sump={float(sump)}, woe={float(woe)}, joy={float(joy)}, awe={float(awe)}")

    @classmethod
    def teardown_class(cls):
        cls.print_imbalance(cls.mcd)
        # FIXME: Because sump is so low, we can't easily kill bad debt by flopping

        # # Start a flop auction
        # self.mcd.flopper.approve(self.mcd.vat.address, hope_directly())
        # self.keeper.check_flop()  # easy way to heal; won't start an auction
        # # assert self.mcd.vow.flop().transact()
        # self.print_imbalance(self.mcd)
        # kick = self.mcd.flopper.kicks()
        # assert kick > 0
        #
        # # Bid on and finish the flop auction
        # lot = Wad.from_number(0.0000001)
        # sump = self.mcd.vow.sump()
        # print(f"reserving {float(sump)} Dai to dent")
        # reserve_dai(self.mcd, self.mcd.collaterals['ETH-C'], self.keeper_address, max(Wad(sump), Wad.from_number(20)))
        # assert self.mcd.flopper.dent(kick, lot, sump).transact(from_address=self.keeper_address)
        # time_travel_by(self.web3, self.mcd.flopper.ttl() + 1)
        # assert self.mcd.flopper.deal(kick).transact()
        # self.print_imbalance(self.mcd)

        joy = cls.mcd.vat.dai(cls.mcd.vow.address)
        ash = cls.mcd.vow.ash()
        woe = cls.mcd.vow.woe()
        if joy > Rad(0):
            cls.keeper.reconcile_debt(joy, ash, woe)

        cls.print_imbalance(cls.mcd)
        # FIXME: sin left after this test will break the flap tests
        # assert self.mcd.vat.sin(self.mcd.vow.address) == Rad(0)

        assert threading.active_count() == 1
