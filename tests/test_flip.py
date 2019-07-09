# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus, bargst
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

import time
import pytest

from datetime import datetime
from mock import MagicMock
from typing import Optional

from auction_keeper.logic import Stance
from auction_keeper.model import Parameters
from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.auctions import Flipper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import web3, wrap_eth, keeper_address, simulate_frob, create_unsafe_cdp, get_collateral_price
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


tend_lot = Wad.from_number(1.2)


# TODO: Figure out how to reset collateral debt ceiling after an auction,
#  that this may be called multiple times.
@pytest.fixture()
def kick(mcd, c: Collateral, gal_address):
    # Bite gal CDP
    unsafe_cdp = create_unsafe_cdp(mcd, c, tend_lot, gal_address)
    assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()
    bites = mcd.cat.past_bite(1)
    assert len(bites) == 1
    return c.flipper.kicks()


@pytest.fixture()
def models(keeper):
    model = MagicMock()
    model.get_stance = MagicMock(return_value=None)
    model_factory = keeper.auctions.model_factory
    model_factory.create_model = MagicMock(return_value=model)
    return (model, model_factory)


def reserve_dai(mcd: DssDeployment, c: Collateral, usr: Address, amount: Wad):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(usr, Address)
    assert isinstance(amount, Wad)

    # Determine how much collateral is needed (for eth, 1 or 2 should suffice for these tests)
    rate = mcd.vat.ilk(c.ilk.name).rate
    collateral_price = get_collateral_price(c)
    assert rate >= Ray.from_number(1)
    assert isinstance(collateral_price, Wad)
    # TODO: Get liquidation ratio (mat) from cat; hardcoded to 1.8 here
    collateral_required = ((amount / collateral_price) * Wad(rate) * Wad.from_number(1.8)) + Wad(10)

    wrap_eth(mcd, usr, collateral_required)
    c.approve(usr)
    assert c.adapter.join(usr, collateral_required).transact(from_address=usr)
    simulate_frob(mcd, c, usr, collateral_required, amount)
    assert mcd.vat.frob(c.ilk, usr, collateral_required, amount).transact(from_address=usr)
    assert mcd.vat.urn(c.ilk, usr).art >= Wad(amount)

# def reserve_and_draw_dai(mcd: DssDeployment, c: Collateral, usr: Address, amount: Wad):
#     reserve_dai(mcd, c, usr, amount)
#     mcd.approve_dai(usr)
#     assert mcd.dai_adapter.exit(usr, amount)


class TestAuctionKeeperFlipper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.keeper_address = keeper_address(self.web3)

    def gem_balance(self, address: Address) -> Wad:
        assert (isinstance(address, Address))
        return Wad(self.gem.balance_of(address))

    @staticmethod
    def simulate_model_output(model, price: Wad, gas_price: Optional[int] = None):
        assert (isinstance(price, Wad))

        model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))

    def simulate_model_bid(self, mcd: DssDeployment, c: Collateral, model: object,
                           price: Wad, gas_price: Optional[int] = None):
        assert (isinstance(mcd, DssDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(price, Wad))
        assert (isinstance(gas_price, int)) or gas_price is None

        flipper = c.flipper
        initial_bid = flipper.bids(1)
        our_bid = price * initial_bid.lot
        reserve_dai(mcd, c, self.keeper_address, our_bid)
        TestAuctionKeeperFlipper.simulate_model_output(model=model, price=price, gas_price=gas_price)

    @staticmethod
    def tend(flipper: Flipper, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(flipper, Flipper))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        current_bid = flipper.bids(id)
        assert current_bid.guy != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert lot == current_bid.lot
        assert bid <= current_bid.tab
        assert bid > current_bid.bid
        assert (bid >= Rad(flipper.beg()) * current_bid.bid) or (bid == current_bid.tab)

        assert flipper.tend(id, lot, bid).transact(from_address=address)

    @staticmethod
    def dent(flipper: Flipper, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(flipper, Flipper))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        current_bid = flipper.bids(id)
        assert current_bid.guy != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert bid == current_bid.bid
        assert bid == current_bid.tab
        assert lot < current_bid.lot
        assert (flipper.beg() * Ray(lot)) <= Ray(current_bid.lot)

        assert flipper.dent(id, lot, bid).transact(from_address=address)

    @staticmethod
    def tend_with_dai(mcd: DssDeployment, c: Collateral, flipper: Flipper, id: int, address: Address, bid: Rad):
        assert (isinstance(mcd, DssDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(flipper, Flipper))
        assert (isinstance(id, int))
        assert (isinstance(bid, Rad))

        flipper.approve(flipper.vat(), approval_function=hope_directly(), from_address=address)
        previous_bid = flipper.bids(id)
        c.approve(address)
        reserve_dai(mcd, c, address, Wad(bid))
        TestAuctionKeeperFlipper.tend(flipper, id, address, previous_bid.lot, bid)

    def test_flipper_address(self, keeper, c):
        assert keeper.flipper.address == c.flipper.address

    #@pytest.mark.skip(reason="Working")
    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, c, kick, mcd,
                                                                               keeper, models):
        # given
        (model, model_factory) = models

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        initial_bid = c.flipper.bids(1)
        # then
        model_factory.create_model.assert_called_once_with(Parameters(flipper=c.flipper.address,
                                                                      flapper=None,
                                                                      flopper=None,
                                                                      id=kick))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == kick
        assert status.flipper == c.flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == Rad.from_number(0)
        assert status.lot == initial_bid.lot
        assert status.tab == initial_bid.tab
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == mcd.cat.address
        assert status.era > 0
        assert status.end < status.era + c.flipper.tau() + 1
        assert status.tic == 0
        assert status.price == Wad(0)

    #@pytest.mark.skip(reason="Working")
    def test_should_provide_model_with_updated_info_after_our_own_bid(self, mcd, c, gal_address, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        previous_bid = flipper.bids(1)
        # then
        assert model.send_status.call_count == 1

        # when
        initial_bid = flipper.bids(1)
        our_price = Wad.from_number(30)
        our_bid = our_price * initial_bid.lot
        reserve_dai(mcd, c, self.keeper_address, our_bid)
        self.simulate_model_output(model=model, price=our_price)
        keeper.check_for_bids()

        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper == flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == Rad(our_price * status.lot)
        assert status.lot == previous_bid.lot
        assert status.tab == previous_bid.tab
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == self.keeper_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == our_price

    #@pytest.mark.skip(reason="Working")
    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, mcd, c, other_address,
                                                                             keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        flipper.approve(flipper.vat(), approval_function=hope_directly(), from_address=other_address)
        previous_bid = flipper.bids(1)
        new_bid_amount = Rad.from_number(80)
        c.approve(other_address)
        reserve_dai(mcd, c, other_address, Wad(new_bid_amount))
        TestAuctionKeeperFlipper.tend(flipper, 1, other_address, previous_bid.lot, new_bid_amount)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper == flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == new_bid_amount
        assert status.lot == previous_bid.lot
        assert status.tab == previous_bid.tab
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == other_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == (Wad(new_bid_amount) / previous_bid.lot)

    @pytest.mark.skip(reason="This works but it's stupid slow")
    def test_should_terminate_model_if_auction_expired_due_to_tau(self, c, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, flipper.tau() + 1)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="Working")
    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self, mcd, c,
                                                                                           other_address,
                                                                                           keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        flipper.approve(flipper.vat(), approval_function=hope_directly(), from_address=other_address)
        previous_bid = flipper.bids(1)
        new_bid_amount = Rad.from_number(85)
        c.approve(other_address)
        reserve_dai(mcd, c, other_address, Wad(new_bid_amount))
        TestAuctionKeeperFlipper.tend(flipper, 1, other_address, previous_bid.lot, new_bid_amount)
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="Working")
    def test_should_terminate_model_if_auction_is_dealt(self, mcd, c, other_address, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        TestAuctionKeeperFlipper.tend_with_dai(mcd, c, flipper, 1, other_address, Rad.from_number(90))
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        flipper.deal(1).transact(from_address=other_address)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="Working")
    def test_should_not_instantiate_model_if_auction_is_dealt(self, mcd, c, other_address, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper
        # and
        TestAuctionKeeperFlipper.tend_with_dai(mcd, c, flipper, 1, other_address, Rad.from_number(90))
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        flipper.deal(1).transact(from_address=other_address)

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    def test_should_not_do_anything_if_no_output_from_model(self, keeper):
        # given
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    @pytest.mark.skip(reason="Working")
    def test_should_make_initial_bid(self, mcd, c, keeper, models, keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        self.simulate_model_bid(mcd, c, model, Wad.from_number(16.0))
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(16.0), 2)

    @pytest.mark.skip(reason="Working")
    def test_should_bid_even_if_there_is_already_a_bidder(self, mcd, c, keeper, models, keeper_address, other_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper
        # and
        self.tend_with_dai(mcd, c, flipper, 1, other_address, Rad.from_number(21))
        assert flipper.bids(1).bid == Rad.from_number(21)

        # when
        self.simulate_model_bid(mcd, c, model, Wad.from_number(23))
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(23), 2)

    @pytest.mark.skip(reason="Working")
    def test_should_sequentially_tend_and_dent_if_price_takes_us_to_the_dent_phrase(self, mcd, c, keeper, models,
                                                                                    keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        our_bid_price = Wad.from_number(150)
        assert our_bid_price * flipper.bids(1).lot > Wad(flipper.bids(1).tab)
        self.simulate_model_bid(mcd, c, model, our_bid_price)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        reserve_dai(mcd, c, keeper_address, Wad(auction.tab))
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot < tend_lot
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad(our_bid_price), 2)

    @pytest.mark.skip(reason="Working")
    def test_should_use_most_up_to_date_price_for_dent_even_if_it_gets_updated_during_tend(self, mcd, c, keeper, models,
                                                                                           keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        first_bid_price = Wad.from_number(140)
        self.simulate_model_bid(mcd, c, model, first_bid_price)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        second_bid_price = Wad.from_number(150)
        self.simulate_model_bid(mcd, c, model, second_bid_price)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot == Wad(auction.bid / Rad(second_bid_price))

    @pytest.mark.skip(reason="Working")
    def test_should_only_tend_if_bid_is_only_slightly_above_tab(self, mcd, c, keeper, models, keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        auction = flipper.bids(1)
        bid_price = Wad(auction.tab) + Wad.from_number(0.1)
        self.simulate_model_bid(mcd, c, model, bid_price)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert flipper.bids(1).bid == auction.tab
        assert flipper.bids(1).lot == tend_lot

    @pytest.mark.skip(reason="Working")
    def test_should_tend_up_to_exactly_tab_if_bid_is_only_slightly_below_tab(self, mcd, c, keeper, models,
                                                                             keeper_address):
        """I assume the point of this test is that the bid increment should be ignored when `tend`ing the `tab`
        to transition the auction into _dent_ phase."""
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        auction = flipper.bids(1)
        assert auction.bid == Rad(0)
        bid_price = (Wad(auction.tab) / tend_lot) - Wad.from_number(0.01)
        self.simulate_model_bid(mcd, c, model, bid_price)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == Rad(bid_price * tend_lot)
        assert auction.lot == tend_lot

        # when
        price_to_reach_tab = Wad(auction.tab / Rad(tend_lot)) + Wad(1)
        self.simulate_model_bid(mcd, c, model, price_to_reach_tab)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(1)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

    @pytest.mark.skip(reason="Working")
    def test_should_overbid_itself_if_model_has_updated_the_price(self, mcd, c, keeper, models, keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        first_bid = Wad.from_number(15.0)
        self.simulate_model_bid(mcd, c, model, first_bid)
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(1).bid == Rad(first_bid * tend_lot)

        # when
        second_bid = Wad.from_number(20.0)
        self.simulate_model_bid(mcd, c, model, second_bid)
        keeper.check_all_auctions()
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(1).bid == Rad(second_bid * tend_lot)

    @pytest.mark.skip(reason="Working")
    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, mcd, c,
                                                                                            keeper, models,
                                                                                            keeper_address):
        # given
        (model, model_factory) = models
        flipper = c.flipper

        # when
        bid_price = Wad.from_number(20.0)
        reserve_dai(mcd, c, keeper_address, bid_price * tend_lot)
        self.simulate_model_output(model=model, price=bid_price, gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(model=model, price=bid_price, gas_price=15)
        # and
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(1).bid == Rad(bid_price * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip(reason="Working")
    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, mcd, c,
                                                                                             keeper, models,
                                                                                             keeper_address):
        # given
        # tab = Wad.from_number(5000),
        # lot = Wad.from_number(100),
        # bid = Wad.from_number(1000)
        (model, model_factory) = models
        flipper = c.flipper

        # when
        self.simulate_model_bid(mcd, c, model, price=Wad.from_number(15.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        keeper.check_all_auctions()
        keeper.check_for_bids()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_bid(mcd, c, model, price=Wad.from_number(20.0), gas_price=15)
        # and
        keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(1).bid == Rad(Wad.from_number(20.0) * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip(reason="needs updating")
    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(20.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(price=Wad.from_number(15.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).bid == Wad.from_number(1500.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip(reason="needs updating")
    def test_should_not_tend_on_rounding_errors_with_small_amounts(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad(5000), Wad(2), Wad(4)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(3.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).bid == Wad(6)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    @pytest.mark.skip(reason="needs updating")
    def test_should_not_dent_on_rounding_errors_with_small_amounts(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad(5000), Wad(10), Wad(5000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(1000.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).lot == Wad(5)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    @pytest.mark.skip(reason="needs updating")
    def test_should_deal_when_we_won_the_auction(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(15.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(15.0), 2)
        assert self.gem_balance(self.keeper_address) == Wad(0)

        # when
        time_travel_by(self.web3, self.flipper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.gem_balance(self.keeper_address) > Wad(0)

    @pytest.mark.skip(reason="needs updating")
    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)
        # and
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1500)).transact(from_address=self.other_address)
        assert self.flipper.bids(1).bid == Wad.from_number(1500)

        # when
        time_travel_by(self.web3, self.flipper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.gem_balance(self.other_address) == Wad(0)

    @pytest.mark.skip(reason="needs updating")
    def test_should_obey_gas_price_provided_by_the_model(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(15.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    @pytest.mark.skip(reason="needs updating")
    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(15.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[
                   0].gasPrice == self.web3.eth.gasPrice
