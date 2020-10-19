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
from tests.conftest import is_safe_safe, other_address, our_address

from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from typing import Optional

bid_size = Wad.from_number(1.2)
bid_size_small = Wad(2000)


@pytest.fixture()
def auction_id(geb, c: Collateral, auction_income_recipient_address) -> int:
    # set to pymaker price
    set_collateral_price(geb, c, Wad.from_number(500))
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
    def teardown_method(self, test_method):
        pass
    def setup_class(self):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        self.web3 = web3()
        self.geb = geb(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.collateral = self.geb.collaterals['ETH-B']
        self.min_auction = self.collateral.collateral_auction_house.auctions_started() + 1
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                     f"--type collateral "
                                     f"--from-block 200 "
                                     f"--min-auction {self.min_auction} "
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

    @staticmethod
    def buy_collateral(collateral_auction_house: FixedDiscountCollateralAuctionHouse, id: int, address: Address,
                       bid_amount: Wad):
        assert (isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(bid_amount, Wad))

        current_bid = collateral_auction_house.bids(id)
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid_amount <= Wad(current_bid.amount_to_raise)

        assert collateral_auction_house.buy_collateral(id, bid_amount).transact(from_address=address)

    @staticmethod
    def buy_collateral_with_system_coin(geb: GfDeployment, c: Collateral, collateral_auction_house: FixedDiscountCollateralAuctionHouse,
                                        id: int, address: Address, bid_amount: Wad):
        assert (isinstance(geb, GfDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(bid_amount, Wad))

        collateral_auction_house.approve(collateral_auction_house.safe_engine(),
                                         approval_function=approve_safe_modification_directly(from_address=address))

        previous_bid = collateral_auction_house.bids(id)
        c.approve(address)
        reserve_system_coin(geb, c, address, bid_amount, extra_collateral=Wad.from_number(2))
        TestAuctionKeeperFixedDiscountCollateralAuctionHouse.buy_collateral(collateral_auction_house, id, address, bid_amount)


    def simulate_model_bid(self, geb: GfDeployment, c: Collateral, model: object,
                          gas_price: Optional[int] = None):
        assert (isinstance(geb, GfDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(gas_price, int)) or gas_price is None

        collateral_auction_house = c.collateral_auction_house
        initial_bid = collateral_auction_house.bids(model.id)
        assert initial_bid.amount_to_sell > Wad(0)
        our_bid = Wad.from_number(500) * initial_bid.amount_to_sell
        reserve_system_coin(geb, c, self.keeper_address, our_bid, extra_collateral=Wad.from_number(2))
        simulate_model_output(model=model, price=Wad.from_number(500), gas_price=gas_price)

    def test_collateral_auction_house_address(self):
        """ Sanity check ensures the keeper fixture is looking at the correct collateral """
        assert self.keeper.collateral_auction_house.address == self.collateral.collateral_auction_house.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_start(self, auction_id, other_address):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        (model, model_factory) = models(self.keeper, auction_id)

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
        assert status.amount_to_sell == initial_bid.amount_to_sell
        assert status.amount_to_raise == initial_bid.amount_to_raise
        assert status.block_time > 0
        assert status.auction_deadline < status.block_time + collateral_auction_house.total_auction_length() + 1

        # cleanup
        TestAuctionKeeperFixedDiscountCollateralAuctionHouse.buy_collateral_with_system_coin(self.geb, self.collateral, collateral_auction_house, auction_id, other_address, Wad.from_number(30))

    #@pytest.mark.skip("tmp")
    def test_should_provide_model_with_updated_info_after_our_partial_bid(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return

        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        initial_status = collateral_auction_house.bids(model.id)
        # then
        assert model.send_status.call_count == 1

        # when bidding less than the full amount
        our_balance = Wad(initial_status.amount_to_raise) / Wad.from_number(2)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, our_balance)

        assert initial_status.amount_to_raise != Rad(0)
        assert self.geb.safe_engine.coin_balance(self.keeper_address) > Rad(0)

        # Make our balance lte half of the auction size
        half_amount_to_raise = initial_status.amount_to_raise / Rad.from_number(2)
        if self.geb.safe_engine.coin_balance(self.keeper_address) >= half_amount_to_raise:
            burn_amount = self.geb.safe_engine.coin_balance(self.keeper_address) - half_amount_to_raise
            assert burn_amount < self.geb.safe_engine.coin_balance(self.keeper_address)
            self.geb.safe_engine.transfer_internal_coins(self.keeper_address, Address("0x0000000000000000000000000000000000000000"), burn_amount).transact()

        assert self.geb.safe_engine.coin_balance(self.keeper_address) <= half_amount_to_raise
        assert self.geb.safe_engine.coin_balance(self.keeper_address) > Rad(0)

        simulate_model_output(model=model, price=None)
        self.keeper.check_for_bids()

        # and checking auction status and sending auction status to model
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()

        # then
        assert model.send_status.call_count > 1

        # ensure our bid was processed
        current_status = collateral_auction_house.bids(model.id)
        assert current_status.amount_to_raise == initial_status.amount_to_raise
        assert current_status.amount_to_sell == initial_status.amount_to_sell
        assert current_status.auction_deadline == initial_status.auction_deadline
        assert current_status.raised_amount == Rad(our_balance)

        # and the last status sent to our model reflects our bid
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house == collateral_auction_house.address
        assert status.surplus_auction_house is None
        assert status.debt_auction_house is None
        assert status.amount_to_sell == initial_status.amount_to_sell
        assert status.amount_to_raise == initial_status.amount_to_raise
        assert status.raised_amount == Rad(our_balance)
        assert status.auction_deadline == initial_status.auction_deadline

        # and auction is still active
        final_status = collateral_auction_house.bids(model.id)
        assert final_status.amount_to_raise == initial_status.amount_to_raise
        assert final_status.amount_to_sell == initial_status.amount_to_sell
        assert final_status.auction_deadline == initial_status.auction_deadline
        assert final_status.raised_amount == Rad(our_balance)

        #cleanup 
        our_balance = Wad(initial_status.amount_to_raise) + Wad(1)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, our_balance)
        assert self.geb.safe_engine.coin_balance(self.keeper_address) >= initial_status.amount_to_raise
        simulate_model_output(model=model, price=None)
        self.keeper.check_for_bids()
        self.keeper.check_all_auctions()
        wait_for_other_threads()

        # ensure auction has been deleted
        current_status = collateral_auction_house.bids(model.id)
        assert current_status.raised_amount == Rad(0)
        assert current_status.sold_amount == Wad(0)
        assert current_status.amount_to_raise == Rad(0)
        assert current_status.amount_to_sell == Wad(0)
        assert current_status.auction_deadline == 0
        assert current_status.raised_amount == Rad(0)

    #@pytest.mark.skip("tmp")
    def test_auction_deleted_after_our_full_bid(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return

        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        initial_status = collateral_auction_house.bids(model.id)
        # then
        assert model.send_status.call_count == 1

        # when bidding the full amount
        our_bid = Wad(initial_status.amount_to_raise) + Wad(1)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, our_bid, Wad.from_number(2))
        assert self.geb.safe_engine.coin_balance(self.keeper_address) >= initial_status.amount_to_raise
        simulate_model_output(model=model, price=None)
        self.keeper.check_for_bids()

        # and checking auction status and sending auction status to model
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()

        # ensure our bid was processed and auction has been deleted
        current_status = collateral_auction_house.bids(model.id)
        assert current_status.raised_amount == Rad(0)
        assert current_status.sold_amount == Wad(0)
        assert current_status.amount_to_raise == Rad(0)
        assert current_status.amount_to_sell == Wad(0)
        assert current_status.auction_deadline == 0
        assert current_status.raised_amount == Rad(0)

    #@pytest.mark.skip("tmp")
    def test_should_provide_model_with_updated_info_after_somebody_else_partial_bids(self, auction_id, other_address):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        collateral_auction_house.approve(collateral_auction_house.safe_engine(),
                                         approval_function=approve_safe_modification_directly(from_address=other_address))
        previous_bid = collateral_auction_house.bids(auction_id)
        new_bid_amount = Wad.from_number(30)
        self.buy_collateral_with_system_coin(self.geb, self.collateral, collateral_auction_house, model.id, other_address, new_bid_amount)
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
        assert status.raised_amount == Rad(new_bid_amount)
        assert status.amount_to_sell == previous_bid.amount_to_sell
        assert status.amount_to_raise == previous_bid.amount_to_raise
        assert status.block_time > 0
        assert status.auction_deadline > status.block_time

    #@pytest.mark.skip("tmp")
    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    #@pytest.mark.skip("tmp")
    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        bid_price = Wad.from_number(20.0)
        reserve_system_coin(self.geb, self.collateral, self.keeper_address, bid_price * bid_size * 2, Wad.from_number(2))
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
        #assert collateral_auction_house.bids(auction_id).raised_amount == Rad(bid_price * bid_size)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    #@pytest.mark.skip("tmp")
    def test_should_obey_gas_price_provided_by_the_model(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.simulate_model_bid(self.geb, self.collateral, model, gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    #@pytest.mark.skip("tmp")
    def test_should_use_default_gas_price_if_not_provided_by_the_model(self, auction_id):
        # given
        collateral_auction_house = self.collateral.collateral_auction_house
        if not isinstance(collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.simulate_model_bid(self.geb, self.collateral, model)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

    @classmethod
    def teardown_class(cls):
        pop_debt_and_settle_debt(web3(), geb(web3()), past_blocks=1200, require_settle_debt=True)
        cls.cleanup_debt(web3(), geb(web3()), other_address(web3()))

    @classmethod
    def cleanup_debt(cls, web3, geb, address):
        # Cancel out debt
        unqueued_unauctioned_debt = geb.accounting_engine.unqueued_unauctioned_debt()
        total_on_auction_debt = geb.accounting_engine.total_on_auction_debt()
        system_coin_needed = unqueued_unauctioned_debt + total_on_auction_debt
        #system_coin_needed = geb.safe_engine.debt_balance(geb.accounting_engine.address)
        if system_coin_needed == Rad(0):
            return
        
        # Need to add Wad(1) when going from Rad to Wad
        reserve_system_coin(geb, geb.collaterals['ETH-A'], our_address(web3), Wad(system_coin_needed) + Wad(1))
        assert geb.safe_engine.coin_balance(our_address(web3)) >= system_coin_needed

        # transfer system coin to accounting engine
        geb.safe_engine.transfer_internal_coins(our_address(web3), geb.accounting_engine.address, system_coin_needed).transact(from_address=our_address(web3))

        system_coin_accounting_engine = geb.safe_engine.coin_balance(geb.accounting_engine.address)

        assert system_coin_accounting_engine >= system_coin_needed
        assert geb.accounting_engine.settle_debt(unqueued_unauctioned_debt).transact()
        assert geb.accounting_engine.unqueued_unauctioned_debt() == Rad(0)
        assert geb.accounting_engine.debt_queue() == Rad(0)

        if geb.accounting_engine.total_on_auction_debt() > Rad(0):
            geb.accounting_engine.cancel_auctioned_debt_with_surplus(total_on_auction_debt).transact()
            assert geb.accounting_engine.total_on_auction_debt() == Rad(0)

        assert geb.safe_engine.debt_balance(geb.accounting_engine.address) == Rad(0)
