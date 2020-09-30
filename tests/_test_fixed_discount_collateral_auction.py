# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 reverendus, bargst, EdNoepel
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
from pyflex import Address
from pyflex.approval import approve_safe_modification_directly
from pyflex.auctions import FixedDiscountCollateralAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import liquidate, create_critical_safe, pop_debt_and_settle_debt, keeper_address, geb, models, \
                           reserve_system_coin, simulate_model_output, web3, set_collateral_price
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from typing import Optional


bid_size = Wad.from_number(1.2)
bid_size_small = Wad(2000)


@pytest.fixture()
def auction_id(geb, c: Collateral, auction_income_recipient_address) -> int:
    # set to pymaker price
    set_collateral_price(geb, c, Wad.from_number(200))

    # Ensure we start with a clean safe
    safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
    assert safe.locked_collateral == Wad(0)
    assert safe.generated_debt == Wad(0)

    # liquidate SAFE
    critical_safe = create_critical_safe(geb, c, bid_size, auction_income_recipient_address)
    return liquidate(geb, c, critical_safe)

@pytest.fixture()
def auction_small(geb, c: Collateral, auction_income_recipient_address) -> int:
    critical_safe = create_critical_safe(geb, c, bid_size_small, auction_income_recipient_address)
    return liquidate(geb, c, critical_safe)


@pytest.mark.timeout(500)
class TestAuctionKeeperFixedDiscountCollateralAuctionHouse(TransactionIgnoringTest):
    def setup_class(self):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        self.web3 = web3()
        self.geb = geb(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.collateral = self.geb.collaterals['ETH-B']
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                     f"--type collateral "
                                     f"--from-block 1 "
                                     f"--collateral-type {self.collateral.collateral_type.name} "
                                     f"--model ./bogus-model.sh"), web3=self.geb.web3)
        self.keeper.approve()

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        self.default_gas_price = self.keeper.gas_price.get_gas_price(0)

    @staticmethod
    def collateral_balance(address: Address, c: Collateral) -> Wad:
        assert (isinstance(address, Address))
        assert (isinstance(c, Collateral))
        return Wad(c.collateral.balance_of(address))

    def simulate_model_bid(self, geb: GfDeployment, c: Collateral, model: object,
                           price: Wad, gas_price: Optional[int] = None):
        assert (isinstance(geb, GfDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(price, Wad))
        assert (isinstance(gas_price, int)) or gas_price is None
        assert price > Wad(0)

        collateral_auction_house = c.collateral_auction_house
        initial_bid = collateral_auction_house.bids(model.id)
        assert initial_bid.amount_to_sell > Wad(0)
        our_bid = price * initial_bid.amount_to_sell
        reserve_system_coin(geb, c, self.keeper_address, our_bid, extra_collateral=Wad.from_number(2))
        simulate_model_output(model=model, price=price, gas_price=gas_price)

    @staticmethod
    def increase_bid_size(collateral_auction_house: FixedDiscountCollateralAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid_amount <= current_bid.amount_to_raise
        assert bid_amount > current_bid.bid_amount
        assert (bid_amount >= Rad(collateral_auction_house.bid_increase()) * current_bid.bid_amount) or (bid_amount == current_bid.amount_to_raise)

        assert collateral_auction_house.increase_bid_size(id, amount_to_sell, bid_amount).transact(from_address=address)

    @staticmethod
    def decrease_sold_amount(collateral_auction_house: FixedDiscountCollateralAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid_amount == current_bid.bid
        assert bid_amount == current_bid.amount_to_raise
        assert amount_to_sell < current_bid.amount_to_sell
        assert collateral_auction_house.bid_increase() * amount_to_sell <= current_bid.amount_to_sell

        assert collateral_auction_house.decrease_sold_amount(id, amount_to_sell, bid_amount).transact(from_address=address)

    @staticmethod
    def increase_bid_size_with_system_coin(geb: GfDeployment, c: Collateral, collateral_auction_house: FixedDiscountCollateralAuctionHouse, id: int, address: Address, bid_amount: Rad):
        assert (isinstance(geb, GfDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(bid_amount, Rad))

        collateral_auction_house.approve(collateral_auction_house.safe_engine(), approval_function=approve_safe_modification_directly(from_address=address))
        previous_bid = collateral_auction_house.bids(id)
        c.approve(address)
        reserve_system_coin(geb, c, address, Wad(bid_amount), extra_collateral=Wad.from_number(2))
        TestAuctionKeeperFixedDiscountCollateralAuctionHouse.increase_bid_size(collateral_auction_house, id, address, previous_bid.amount_to_sell, bid_amount)

    def test_collateral_auction_house_address(self):
        """ Sanity check ensures the keeper fixture is looking at the correct collateral """
        assert self.keeper.collateral_auction_house.address == self.collateral.collateral_auction_house.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_start(self, auction_id, other_address):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        initial_bid = self.collateral.collateral_auction_house.bids(auction_id)
        # then
        model_factory.create_model.assert_called_once_with(Parameters(collateral_auction_house=collateral_auction_house.address,
                                                                      surplus_auction_house=None,
                                                                      debt_auction_house=None,
                                                                      id=auction_id))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house == collateral_auction_house.address
        assert status.surplus_auction_house is None
        assert status.debt_auction_house is None
        assert status.bid_amount == Rad.from_number(0)
        assert status.amount_to_sell == initial_bid.amount_to_sell
        assert status.amount_to_raise == initial_bid.amount_to_raise
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == self.geb.liquidation_engine.address
        assert status.era > 0
        assert status.auction_deadline < status.era + collateral_auction_house.total_auction_length() + 1
        assert status.bid_expiry == 0
        assert status.price == Wad(0)

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        self.keeper.check_all_auctions()
        TestAuctionKeeperFixedDiscountCollateralAuctionHouse.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, Rad.from_number(30))
        collateral_auction_house.settle_auction(auction_id).transact(from_address=other_address)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        previous_bid = collateral_auction_house.bids(model.id)
        # then
        assert model.send_status.call_count == 1

        # when
        initial_bid = collateral_auction_house.bids(auction_id)
        our_price = Wad.from_number(20)
        our_bid = our_price * initial_bid.amount_to_sell
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, our_bid)
        simulate_model_output(model=model, price=our_price)
        self.keeper.check_for_bids()

        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house == collateral_auction_house.address
        assert status.surplus_auction_house is None
        assert status.debt_auction_house is None
        assert status.bid_amount == Rad(our_price * status.amount_to_sell)
        assert status.amount_to_sell == previous_bid.amount_to_sell
        assert status.amount_to_raise == previous_bid.amount_to_raise
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == self.keeper_address
        assert status.era > 0
        assert status.auction_deadline > status.era
        assert status.bid_expiry > status.era
        assert status.price == our_price

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, auction_id, other_address):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        collateral_auction_house.approve(collateral_auction_house.safe_engine(), approval_function=approve_safe_modification_directly(from_address=other_address))
        previous_bid = collateral_auction_house.bids(auction_id)
        new_bid_amount = Rad.from_number(30)
        self.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, model.id, other_address, new_bid_amount)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house == collateral_auction_house.address
        assert status.surplus_auction_house is None
        assert status.debt_auction_house is None
        assert status.bid_amount == new_bid_amount
        assert status.amount_to_sell == previous_bid.amount_to_sell
        assert status.amount_to_raise == previous_bid.amount_to_raise
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == other_address
        assert status.era > 0
        assert status.auction_deadline > status.era
        assert status.bid_expiry > status.era
        assert status.price == (Wad(new_bid_amount) / previous_bid.amount_to_sell)

    def test_should_restart_if_auction_expired_due_to_total_auction_length(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, collateral_auction_house.total_auction_length() + 1)
        # and
        self.simulate_model_bid(self.geb, self.collateral, model, Wad.from_number(15.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        model.terminate.assert_not_called()
        auction = collateral_auction_house.bids(auction_id)
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(15.0), 2)

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        self.keeper.check_all_auctions()
        model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_bid_duration_and_somebody_else_won_it(self, auction_id, other_address):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        collateral_auction_house.approve(collateral_auction_house.safe_engine(), approval_function=approve_safe_modification_directly(from_address=other_address))
        new_bid_amount = Rad.from_number(30)
        self.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, new_bid_amount)
        # and
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

        # cleanup
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_terminate_model_if_auction_is_settled(self, auction_id, other_address):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, Rad.from_number(30))
        # and
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        # and
        collateral_auction_house.settle_auction(auction_id).transact(from_address=other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_not_instantiate_model_if_auction_is_settled(self, auction_id, other_address):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house
        # and
        TestAuctionKeeperFixedDiscountCollateralAuctionHouse.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, Rad.from_number(30))
        # and
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        # and
        collateral_auction_house.settle_auction(auction_id).transact(from_address=other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    def test_should_make_initial_bid(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        self.simulate_model_bid(self.geb, self.collateral, model, Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(16.0), 2)

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_bid_even_if_there_is_already_a_bidder(self, auction_id, other_address):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house
        # and
        self.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, Rad.from_number(21))
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad.from_number(21)

        # when
        self.simulate_model_bid(self.geb, self.collateral, model, Wad.from_number(23))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)

        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(23), 2)

    def test_should_sequentially_increase_bid_size_and_decrease_sold_amount_if_price_takes_us_to_the_decrease_sold_amount_phrase(self, auction_id, keeper_address):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        our_bid_price = Wad.from_number(150)
        assert our_bid_price * collateral_auction_house.bids(auction_id).amount_to_sell > Wad(collateral_auction_house.bids(1).amount_to_raise)

        self.simulate_model_bid(self.geb, self.collateral, model, our_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == bid_size

        # when
        reserve_system_coin(self.geb, self.collateral, keeper_address, Wad(auction.amount_to_raise))
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell < bid_size
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad(our_bid_price), 2)

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_use_most_up_to_date_price_for_decrease_sold_amount_even_if_it_gets_updated_during_increase_bid_size(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        first_bid_price = Wad.from_number(140)
        self.simulate_model_bid(self.geb, self.collateral, model, first_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == bid_size

        # when
        second_bid_price = Wad.from_number(150)
        self.simulate_model_bid(self.geb, self.collateral, model, second_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == Wad(auction.bid_amount / Rad(second_bid_price))

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_only_increase_bid_size_if_bid_is_only_slightly_above_amount_to_raise(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        auction = collateral_auction_house.bids(auction_id)
        bid_price = Wad(auction.amount_to_raise) + Wad.from_number(0.1)
        self.simulate_model_bid(self.geb, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == bid_size

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == bid_size

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_increase_bid_size_up_to_exactly_amount_to_raise_if_bid_is_only_slightly_below_amount_to_raise(self, auction_id):
        """I assume the point of this test is that the bid increment should be ignored when `increase_bid_size`ing the `amount_to_raise`
        to transition the auction into _decrease_sold_amount_ phase."""
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == Rad(0)
        bid_price = Wad(auction.amount_to_raise / Rad(bid_size)) - Wad.from_number(0.01)
        self.simulate_model_bid(self.geb, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount < auction.amount_to_raise
        assert round(auction.bid_amount, 2) == round(Rad(bid_price * bid_size), 2)
        assert auction.amount_to_sell == bid_size

        # when
        price_to_reach_amount_to_raise = Wad(auction.amount_to_raise / Rad(bid_size)) + Wad(1)
        self.simulate_model_bid(self.geb, self.collateral, model, price_to_reach_amount_to_raise)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = collateral_auction_house.bids(auction_id)
        assert auction.bid_amount == auction.amount_to_raise
        assert auction.amount_to_sell == bid_size

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_overbid_itself_if_model_has_updated_the_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        first_bid = Wad.from_number(15.0)
        self.simulate_model_bid(self.geb, self.collateral, model, first_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(first_bid * bid_size)

        # when
        second_bid = Wad.from_number(20.0)
        self.simulate_model_bid(self.geb, self.collateral, model, second_bid)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(second_bid * bid_size)

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        bid_price = Wad.from_number(20.0)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, bid_price * bid_size * 2)
        simulate_model_output(model=model, price=bid_price, gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=bid_price, gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(bid_price * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, Wad.from_number(35.0) * bid_size * 2)
        simulate_model_output(model=model, price=Wad.from_number(15.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(20.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(Wad.from_number(20.0) * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self, auction_id):
        """ Assuming we want all bids to be submitted as soon as output from the model is parsed,
        this test seems impractical.  In real applications, the model would be unable to submit a lower bid. """
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        collateral_auction_house = self.collateral.collateral_auction_house
        assert self.geb.web3 == self.web3

        # when
        bid_price = Wad.from_number(20.0)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, bid_price * bid_size)
        simulate_model_output(model=model, price=Wad.from_number(20.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(15.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(Wad.from_number(15.0) * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_not_increase_bid_size_on_rounding_errors_with_small_amounts(self, auction_small):
        # given
        (model, model_factory) = models(self.keeper, auction_small)
        collateral_auction_house = self.collateral.collateral_auction_house

        # when
        bid_price = Wad.from_number(3.0)
        self.simulate_model_bid(self.geb, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_small).bid_amount == Rad(bid_price * bid_size_small)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_not_decrease_sold_amount_on_rounding_errors_with_small_amounts(self):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        auction_small = collateral_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_small)

        # when
        auction = collateral_auction_house.bids(auction_small)
        bid_price = Wad(auction.amount_to_raise / Rad(bid_size_small))
        self.simulate_model_bid(self.geb, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_small).amount_to_sell == auction.amount_to_sell

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_settle_auction_when_we_won_the_auction(self):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        auction_id = collateral_auction_house.auctions_started()

        # when
        collateral_before = self.collateral.collateral.balance_of(self.keeper_address)

        # when
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        lot_won = collateral_auction_house.bids(auction_id).amount_to_sell
        assert lot_won > Wad(0)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        assert self.collateral.adapter.exit(self.keeper_address, lot_won).transact(from_address=self.keeper_address)
        # then
        collateral_after = self.collateral.collateral.balance_of(self.keeper_address)
        assert collateral_before < collateral_after

    def test_should_not_settle_auction_when_auction_finished_but_somebody_else_won(self, auction_id, other_address):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        # and
        bid_amount = Rad.from_number(30)
        self.increase_bid_size_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, bid_amount)
        assert collateral_auction_house.bids(auction_id).bid_amount == bid_amount

        # when
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then ensure the bid hasn't been deleted
        assert collateral_auction_house.bids(auction_id).bid_amount == bid_amount

        # cleanup
        assert collateral_auction_house.settle_auction(auction_id).transact()
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(0)

    def test_should_obey_gas_price_provided_by_the_model(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.simulate_model_bid(self.geb, self.collateral, model, price=Wad.from_number(15.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.collateral.collateral_auction_house.bids(auction_id).bid_amount == Rad(Wad.from_number(15.0) * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.simulate_model_bid(self.geb, self.collateral, model, price=Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(Wad.from_number(16.0) * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    def test_should_change_gas_strategy_when_model_output_changes(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        first_bid = Wad.from_number(3)
        self.simulate_model_bid(self.geb, self.collateral, model=model, price=first_bid, gas_price=2000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 2000

        # when
        second_bid = Wad.from_number(6)
        self.simulate_model_bid(self.geb, self.collateral, model=model, price=second_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(second_bid * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # when
        third_bid = Wad.from_number(9)
        new_gas_price = int(self.default_gas_price*1.25)
        self.simulate_model_bid(self.geb, self.collateral, model=model, price=third_bid, gas_price=new_gas_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert collateral_auction_house.bids(auction_id).bid_amount == Rad(third_bid * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == new_gas_price

        # cleanup
        time_travel_by(self.web3, collateral_auction_house.bid_duration() + 1)
        assert collateral_auction_house.settle_auction(auction_id).transact()

    @classmethod
    def teardown_class(cls):
        pop_debt_and_settle_debt(web3(), geb(web3()), past_blocks=1200, require_settle_debt=False)
