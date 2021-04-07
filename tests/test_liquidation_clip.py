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
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import create_unsafe_cdp, gal_address, get_collateral_price, keeper_address, liquidate_urn, mcd, \
    models, other_address, purchase_dai, repay_urn, reserve_dai, set_collateral_price, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


@pytest.fixture(scope="session")
def collateral_clip(mcd):
    return mcd.collaterals['ETH-B']


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


class ClipperTest(TransactionIgnoringTest):
    @classmethod
    def setup_class(cls):
        cls.web3 = web3()
        cls.mcd = mcd(cls.web3)
        cls.collateral = collateral_clip(cls.mcd)
        cls.clipper = cls.collateral.clipper
        cls.keeper_address = keeper_address(cls.web3)
        cls.gal_address = gal_address(cls.web3)
        cls.other_address = other_address(cls.web3)

    def take_with_dai(self, id: int, price: Ray, address: Address):
        assert isinstance(id, int)
        assert isinstance(price, Ray)
        assert isinstance(address, Address)

        lot = self.clipper.sales(id).lot
        assert lot > Wad(0)

        cost = Wad(price * Ray(lot))
        logging.debug(f"reserving {cost} Dai to bid on auction {id}")
        reserve_dai(self.mcd, self.collateral, address, cost)
        assert self.mcd.vat.dai(address) >= Rad(cost)

        logging.debug(f"attempting to take clip {id} at {price}")
        self.clipper.validate_take(id, lot, price, address)
        assert self.clipper.take(id, lot, price, address).transact(from_address=address)

    def take_below_price(self, id: int, our_price: Ray, address: Address):
        assert isinstance(id, int)
        assert isinstance(our_price, Ray)
        assert isinstance(address, Address)

        (needs_redo, auction_price, lot, tab) = self.clipper.status(id)
        while lot > Wad(0) and not needs_redo:
            if auction_price < our_price:
                self.take_with_dai(id, our_price, address)
                break
            time_travel_by(self.web3, 1)
            (needs_redo, auction_price, lot, tab) = self.clipper.status(id)
        assert not needs_redo
        assert self.clipper.sales(id).lot == Wad(0)

    def clean_up_dead_auctions(self, address: Address):
        assert isinstance(self.collateral, Collateral)
        assert isinstance(address, Address)

        for kick in range(1, self.clipper.kicks() + 1):
            (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)
            if needs_redo:
                print(f"Cleaning up dangling {self.collateral.ilk.name} clip auction {kick}")
                purchase_dai(Wad(tab) + Wad(1), address)
                assert self.mcd.dai_adapter.join(address, Wad(tab) + Wad(1)).transact(from_address=address)
                assert self.mcd.vat.dai(address) >= tab
                assert self.clipper.redo(kick, address).transact()
                bid_price = Ray(tab / Rad(lot))
                while auction_price > bid_price:
                    time_travel_by(self.mcd.web3, 1)
                    (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)
                self.clipper.validate_take(kick, lot, bid_price, address)
                assert self.clipper.take(kick, lot, bid_price).transact(from_address=address)
            (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)
            assert not needs_redo


@pytest.mark.timeout(60)
class TestAuctionKeeperBark(ClipperTest):
    @classmethod
    def setup_class(cls):
        super().setup_class()
        cls.keeper = AuctionKeeper(args=args(f"--eth-from {cls.keeper_address.address} "
                                     f"--type clip "
                                     f"--from-block 1 "
                                     f"--ilk {cls.collateral.ilk.name} "
                                     f"--kick-only"), web3=cls.mcd.web3)
        cls.keeper.approve()

        assert get_collateral_price(cls.collateral) == Wad.from_number(200)

        # Keeper won't bid with a 0 Dai balance
        if cls.mcd.vat.dai(cls.keeper_address) == Rad(0):
            purchase_dai(Wad.from_number(20), cls.keeper_address)
        assert cls.mcd.dai_adapter.join(cls.keeper_address, Wad.from_number(20)).transact(
            from_address=cls.keeper_address)

    def test_bark_and_clip(self, mcd, gal_address):
        # setup
        repay_urn(mcd, self.collateral, gal_address)

        # given 21 Dai / (200 price * 2.0 mat) == 0.21 vault size
        unsafe_cdp = create_unsafe_cdp(mcd, self.collateral, Wad.from_number(0.21), gal_address, draw_dai=False)
        assert self.clipper.active_count() == 0
        kicks_before = self.clipper.kicks()

        # when
        self.keeper.check_vaults()
        wait_for_other_threads()

        # then
        print(mcd.dog.past_barks(10))
        assert len(mcd.dog.past_barks(10)) > 0
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe vault has been barked
        assert urn.ink == Wad(0)  # unsafe vault is now safe ...
        assert self.clipper.kicks() == kicks_before + 1  # One auction started

        # cleanup
        kick = self.collateral.clipper.kicks()
        (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)
        bid_price = Ray(get_collateral_price(self.collateral))
        self.take_below_price(kick, bid_price, self.keeper_address)

    def test_should_not_bark_dusty_urns(self, mcd, gal_address):
        # given a lot smaller than the dust limit
        urn = mcd.vat.urn(self.collateral.ilk, gal_address)
        assert urn.art < Wad(self.collateral.ilk.dust)
        kicks_before = self.collateral.clipper.kicks()

        # then ensure the keeper does not bark it
        self.keeper.check_vaults()
        wait_for_other_threads()
        kicks_after = self.collateral.clipper.kicks()
        assert kicks_before == kicks_after

    @classmethod
    def teardown_class(cls):
        set_collateral_price(cls.mcd, cls.collateral, Wad.from_number(200.00))
        assert threading.active_count() == 1


@pytest.mark.timeout(500)
class TestAuctionKeeperClipper(ClipperTest):
    @classmethod
    def setup_class(cls):
        super().setup_class()
        assert cls.collateral.clipper
        assert not cls.collateral.flipper
        cls.keeper = AuctionKeeper(args=args(f"--eth-from {cls.keeper_address.address} "
                                              f"--type clip "
                                              f"--from-block 1 "
                                              f"--ilk {cls.collateral.ilk.name} "
                                              f"--model ./bogus-model.sh"), web3=cls.mcd.web3)
        cls.keeper.approve()

        # Clean up the urn used for bark testing such that it doesn't impact our flip tests
        assert get_collateral_price(cls.collateral) == Wad.from_number(200)
        if not repay_urn(cls.mcd, cls.collateral, cls.gal_address):
            liquidate_urn(cls.mcd, cls.collateral, cls.gal_address, cls.keeper_address)

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

    def simulate_model_bid(self, model, price: Ray, reserve_dai_for_bid=True):
        assert isinstance(price, Ray)
        assert price > Ray(0)

        assert model.id > 0
        sale = self.clipper.sales(model.id)
        assert sale.lot > Wad(0)

        our_bid = Ray(sale.lot) * price
        if reserve_dai_for_bid:
            reserve_dai(self.mcd, self.collateral, self.keeper_address, Wad(our_bid) + Wad(1))
        simulate_model_output(model=model, price=Wad(price))

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

    def test_should_take_if_model_price_updated(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        (needs_redo, price, initial_lot, initial_tab) = self.clipper.status(kick)

        # when initial model price is too low
        bad_price = price - Ray.from_number(30)
        self.simulate_model_bid(model, bad_price)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()

        # then ensure no bid was submitted
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        assert lot == initial_lot
        assert tab == initial_tab

        # when model price becomes appropriate
        good_price = price + Ray.from_number(30)
        self.simulate_model_bid(model, good_price)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()

        # then ensure our bid was submitted
        our_take: Clipper.TakeLog = self.last_log()
        assert our_take.id == kick
        assert our_take.price <= good_price
        # and that the auction finished
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        assert lot == Wad(0)

    def test_should_take_partial_if_insufficient_dai_available(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        (needs_redo, price, initial_lot, initial_tab) = self.clipper.status(kick)
        assert initial_lot == Wad.from_number(1)
        # and we exit all Dai out of the Vat
        assert self.mcd.dai_adapter.exit(self.keeper_address, Wad(self.mcd.vat.dai(self.keeper_address)))\
            .transact(from_address=self.keeper_address)

        # when we have less Dai than we need to cover the auction
        our_price = Ray.from_number(153)
        assert our_price < price
        dai_needed = initial_lot * Wad(our_price)
        initial_dai_available = dai_needed / Wad.from_number(2)
        reserve_dai(self.mcd, self.collateral, self.keeper_address, initial_dai_available)
        assert Wad(self.mcd.vat.dai(self.keeper_address)) < dai_needed

        # then ensure we don't bid when the price is too high
        self.simulate_model_bid(model, our_price, reserve_dai_for_bid=False)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        assert lot == initial_lot
        assert tab == initial_tab

        # when we wait for the price to become appropriate
        while lot > Wad(0):
            time_travel_by(self.web3, 1)
            (needs_redo, auction_price, lot, tab) = self.clipper.status(kick)
            if auction_price < our_price:
                break

        # then ensure our bid is submitted using available Dai
        # self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        (needs_redo, price, lot, tab) = self.clipper.status(kick)
        assert lot < initial_lot
        our_take = self.last_log()
        assert isinstance(our_take, Clipper.TakeLog)
        assert our_take.lot == initial_lot / Wad.from_number(2)
        assert Wad(self.mcd.vat.dai(self.keeper_address)) < initial_dai_available

        # cleanup
        self.take_below_price(kick, price, self.keeper_address)

    def teardown_method(self):
        set_collateral_price(self.mcd, self.collateral, Wad.from_number(200.00))

    @classmethod
    def teardown_class(cls):
        assert threading.active_count() == 1
