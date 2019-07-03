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
from web3 import Web3, HTTPProvider

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from tests.conftest import wrap_eth
from pymaker import Address, Contract
from pymaker.approval import directly, hope_directly
from pymaker.auctions import Flipper
from pymaker.deployment import DssDeployment
from pymaker.dss import Urn, Collateral
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSToken
from tests.conftest import get_collateral_price, simulate_frob, create_unsafe_cdp
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


@pytest.fixture()
def bid_id(mcd, c: Collateral, gal_address):
    # Bite gal CDP
    unsafe_cdp = create_unsafe_cdp(mcd, c, gal_address)
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

    collateral_required = Wad.from_number(1)  # amount / get_collateral_price(c)
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


# @pytest.mark.skip(reason="Need to point at testchain with proper MCD deployment")
class TestAuctionKeeperFlipper(TransactionIgnoringTest):
    def gem_balance(self, address: Address) -> Wad:
        assert (isinstance(address, Address))
        return Wad(self.gem.balance_of(address))

    @staticmethod
    def simulate_model_output(model, price: Wad, gas_price: Optional[int] = None):
        model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))

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

    def test_flipper_address(self, keeper, c):
        assert keeper.flipper.address == c.flipper.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, c, bid_id, mcd,
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
                                                                      id=bid_id))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == bid_id
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

    def test_should_provide_model_with_updated_info_after_our_own_bid(self, mcd, c, gal_address, keeper_address,
                                                                      keeper, models):
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
        reserve_dai(mcd, c, keeper_address, our_bid)
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
        assert status.guy == keeper_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == our_price


    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, mcd, c,
                                                                             gal_address, keeper_address, other_address,
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
        #assert flipper.tend(1, previous_bid.lot, new_bid_amount).transact(from_address=other_address)
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

    @pytest.mark.skip(reason="needs updating")
    def test_should_terminate_model_if_auction_expired_due_to_tau(self, web3, c, gal_address, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper
        flipper.kick(gal_address, gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=gal_address)

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(web3, flipper.tau() + 5)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="needs updating")
    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self, web3, c,
                                                                                           gal_address, other_address,
                                                                                           keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper
        flipper.kick(gal_address, gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=gal_address)

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=other_address)
        # and
        time_travel_by(web3, flipper.ttl() + 5)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="needs updating")
    def test_should_terminate_model_if_auction_is_dealt(self, web3, c, gal_address, other_address, keeper, models):
        # given
        (model, model_factory) = models
        flipper = c.flipper
        flipper.kick(gal_address, gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=gal_address)

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=other_address)
        # and
        time_travel_by(web3, flipper.ttl() + 5)
        # and
        flipper.deal(1).transact(from_address=other_address)
        # and
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip(reason="needs updating")
    def test_should_not_instantiate_model_if_auction_is_dealt(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)
        # and
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flipper.ttl() + 5)
        # and
        self.flipper.deal(1).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_not_called()

    @pytest.mark.skip(reason="needs updating")
    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    @pytest.mark.skip(reason="needs updating")
    def test_should_make_initial_bid(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(16.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)
        # and
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=self.other_address)
        assert self.flipper.bids(1).bid == Wad.from_number(1600)

        # when
        self.simulate_model_output(price=Wad.from_number(19.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(1900)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(19.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_sequentially_tend_and_dent_if_price_takes_us_to_the_dent_phrase(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(80.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(50.0), 2)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(62.5)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(80.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_use_most_up_to_date_price_for_dent_even_if_it_gets_updated_during_tend(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(80.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(50.0), 2)

        # when
        self.simulate_model_output(price=Wad.from_number(100.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(50.0)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(100.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_only_tend_if_bid_is_only_slightly_above_tab(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(50.1))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(50.0), 2)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(50.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_tend_up_to_exactly_tab_if_bid_is_only_slightly_below_tab(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(49.99))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(4999)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(49.99), 2)

        # when
        self.simulate_model_output(price=Wad.from_number(50.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(5000)
        assert self.flipper.bids(1).lot == Wad.from_number(100)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(50.0), 2)

    @pytest.mark.skip(reason="needs updating")
    def test_should_overbid_itself_if_model_has_updated_the_price(self):
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
        assert self.flipper.bids(1).bid == Wad.from_number(1500.0)

        # when
        self.simulate_model_output(price=Wad.from_number(20.0))
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).bid == Wad.from_number(2000.0)

    @pytest.mark.skip(reason="needs updating")
    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self):
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
        self.simulate_model_output(price=Wad.from_number(20.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).bid == Wad.from_number(2000.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip(reason="needs updating")
    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(15.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(price=Wad.from_number(20.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flipper.bids(1).bid == Wad.from_number(2000.0)
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
