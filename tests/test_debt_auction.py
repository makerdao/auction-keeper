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
import time

from auction_keeper.gas import DynamicGasPrice
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from auction_keeper.strategy import DebtAuctionStrategy
from datetime import datetime, timezone
from pyflex import Address
from pyflex.approval import approve_safe_modification_directly
from pyflex.auctions import DebtAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import liquidate, create_critical_safe, pop_debt_and_settle_debt, auction_income_recipient_address, keeper_address, geb, \
    models, our_address, other_address, reserve_system_coin, simulate_model_output, web3
from tests.conftest import is_safe_safe
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from web3 import Web3


@pytest.fixture()
def auction_id(web3: Web3, geb: GfDeployment, auction_income_recipient_address, other_address) -> int:

    total_surplus = geb.safe_engine.coin_balance(geb.accounting_engine.address)
    unqueued_unauctioned_debt = (geb.safe_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - geb.accounting_engine.total_on_auction_debt()
    print(f'total_surplus={str(total_surplus)[:6]}, unqueued_unauctioned_debt={str(unqueued_unauctioned_debt)[:6]}')

    if unqueued_unauctioned_debt < total_surplus or (unqueued_unauctioned_debt == Rad(0) and total_surplus == Rad(0)):
        # Liquidate SAFE
        c = geb.collaterals['ETH-B']
        critical_safe= create_critical_safe(geb, c, Wad.from_number(2), other_address, draw_system_coin=False)
        collateral_auction_id = liquidate(geb, c, critical_safe)

        # Generate some system coin, bid on and win the collateral auction without covering all the debt
        reserve_system_coin(geb, c, auction_income_recipient_address, Wad.from_number(100), extra_collateral=Wad.from_number(1.1))
        c.collateral_auction_house.approve(geb.safe_engine.address, approval_function=approve_safe_modification_directly(from_address=auction_income_recipient_address))
        current_bid = c.collateral_auction_house.bids(collateral_auction_id)
        bid_amount = Rad.from_number(1.9)
        assert geb.safe_engine.coin_balance(auction_income_recipient_address) > bid_amount
        assert c.collateral_auction_house.increase_bid_size(collateral_auction_id, current_bid.amount_to_sell, bid_amount).transact(from_address=auction_income_recipient_address)
        time_travel_by(web3, c.collateral_auction_house.bid_duration()+1)
        assert c.collateral_auction_house.settle_auction(collateral_auction_id).transact()

    pop_debt_and_settle_debt(web3, geb, past_blocks=1200, cancel_auctioned_debt=False)

    # Start the debt auction
    unqueued_unauctioned_debt = (geb.safe_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - geb.accounting_engine.total_on_auction_debt()
    assert geb.accounting_engine.debt_auction_bid_size() <= unqueued_unauctioned_debt
    assert geb.safe_engine.coin_balance(geb.accounting_engine.address) == Rad(0)
    assert geb.accounting_engine.auction_debt().transact(from_address=auction_income_recipient_address)
    return geb.debt_auction_house.auctions_started()


@pytest.mark.timeout(600)
class TestAuctionKeeperDebtAuction(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.our_address = our_address(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.other_address = other_address(self.web3)
        self.auction_income_recipient_address = auction_income_recipient_address(self.web3)
        self.geb = geb(self.web3)
        self.debt_auction_house = self.geb.debt_auction_house
        self.debt_auction_house.approve(self.geb.safe_engine.address, approval_function=approve_safe_modification_directly(from_address=self.keeper_address))
        self.debt_auction_house.approve(self.geb.safe_engine.address, approval_function=approve_safe_modification_directly(from_address=self.other_address))

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--type debt "
                                              f"--from-block 1 "
                                              f"--model ./bogus-model.sh"), web3=self.web3)
        self.keeper.approve()

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        self.default_gas_price = self.keeper.gas_price.get_gas_price(0)

        reserve_system_coin(self.geb, self.geb.collaterals['ETH-C'], self.keeper_address, Wad.from_number(200.00000))
        reserve_system_coin(self.geb, self.geb.collaterals['ETH-C'], self.other_address, Wad.from_number(200.00000))

        self.debt_auction_bid_size = self.geb.accounting_engine.debt_auction_bid_size()  # Rad

    def decrease_sold_amount(self, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        assert self.debt_auction_house.contract_enabled() == 1

        current_bid = self.debt_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid_amount == current_bid.bid_amount
        assert Wad(0) < amount_to_sell < current_bid.amount_to_sell
        assert self.debt_auction_house.bid_decrease() * amount_to_sell <= current_bid.amount_to_sell

        assert self.debt_auction_house.decrease_sold_amount(id, amount_to_sell, bid_amount).transact(from_address=address)

    def amount_to_sell_implies_price(self, auction_id: int, price: Wad) -> bool:
        return round(Rad(self.debt_auction_house.bids(auction_id).amount_to_sell), 2) == round(self.debt_auction_bid_size / Rad(price), 2)

    def test_should_detect_debt_auction(self, web3, c, geb, other_address, keeper_address):
        # given a count of debt auctions
        reserve_system_coin(geb, c, keeper_address, Wad.from_number(230))
        auctions_started = geb.debt_auction_house.auctions_started()

        # and an undercollateralized SAFE is liquidated
        critical_safe = create_critical_safe(geb, c, Wad.from_number(1), other_address, draw_system_coin=False)
        assert geb.liquidation_engine.liquidate_safe(critical_safe.collateral_type, critical_safe).transact()

        # when the auction ends without debt being covered
        time_travel_by(web3, c.collateral_auction_house.total_auction_length() + 1)

        # then ensure testchain is in the appropriate state
        total_surplus = geb.safe_engine.coin_balance(geb.accounting_engine.address)
        total_debt = geb.safe_engine.debt_balance(geb.accounting_engine.address)
        unqueued_unauctioned_debt = (geb.safe_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - geb.accounting_engine.total_on_auction_debt()
        debt_queue = geb.accounting_engine.debt_queue()
        debt_auction_bid_size = geb.accounting_engine.debt_auction_bid_size()
        wait = geb.accounting_engine.pop_debt_delay()
        assert total_surplus < total_debt
        assert unqueued_unauctioned_debt + debt_queue >= debt_auction_bid_size
        assert wait == 0

        # when
        self.keeper.check_debt()
        wait_for_other_threads()

        # then ensure another debt auction was started
        auction_id = geb.debt_auction_house.auctions_started()
        assert auction_id == auctions_started + 1

        # clean up by letting someone else bid and waiting until the auction ends
        self.decrease_sold_amount(auction_id, self.other_address, Wad.from_number(0.000012), self.debt_auction_bid_size)
        time_travel_by(web3, geb.debt_auction_house.bid_duration() + 1)

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_start(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once_with(Parameters(collateral_auction_house=None,
                                                                      surplus_auction_house=None,
                                                                      debt_auction_house=self.debt_auction_house.address,
                                                                      id=auction_id))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house is None
        assert status.debt_auction_house == self.debt_auction_house.address
        assert status.bid_amount > Rad.from_number(0)
        assert status.amount_to_sell == self.geb.accounting_engine.initial_debt_auction_minted_tokens()
        assert status.amount_to_raise is None
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == self.geb.accounting_engine.address
        assert status.era > 0
        assert status.auction_deadline < status.era + self.debt_auction_house.total_auction_length() + 1
        assert status.bid_expiry == 0
        assert status.price == Wad(status.bid_amount / Rad(status.amount_to_sell))

    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        auction_id = self.debt_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        price = Wad.from_number(50.0)
        simulate_model_output(model=model, price=price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        last_bid = self.debt_auction_house.bids(auction_id)
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house is None
        assert status.debt_auction_house == self.debt_auction_house.address
        assert status.bid_amount == last_bid.bid_amount
        assert status.amount_to_sell == Wad(last_bid.bid_amount / Rad(price))
        assert status.amount_to_raise is None
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == self.keeper_address
        assert status.era > 0
        assert status.auction_deadline > status.era
        assert status.bid_expiry > status.era
        assert status.price == price

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        amount_to_sell = Wad.from_number(0.0000001)
        assert self.debt_auction_house.decrease_sold_amount(auction_id, amount_to_sell, self.debt_auction_bid_size).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house is None
        assert status.debt_auction_house == self.debt_auction_house.address
        assert status.bid_amount == self.debt_auction_bid_size
        assert status.amount_to_sell == amount_to_sell
        assert status.amount_to_raise is None
        assert status.bid_increase > Wad.from_number(1)
        assert status.high_bidder == self.other_address
        assert status.era > 0
        assert status.auction_deadline > status.era
        assert status.bid_expiry > status.era
        assert status.price == Wad(self.debt_auction_bid_size / Rad(amount_to_sell))

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_restart_auction_if_auction_expired_due_to_total_auction_length(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, self.debt_auction_house.total_auction_length() + 1)
        # and
        simulate_model_output(model=model, price=Wad.from_number(555.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        model.terminate.assert_not_called()
        auction = self.debt_auction_house.bids(auction_id)
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(555.0), 2)

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        model_factory.create_model.assert_called_once()
        self.keeper.check_all_auctions()
        model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_bid_duration_and_somebody_else_won_it(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.decrease_sold_amount(auction_id, self.other_address, Wad.from_number(0.000015), self.debt_auction_bid_size)
        # and
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

        # cleanup
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_terminate_model_if_auction_is_settled(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.decrease_sold_amount(auction_id, self.other_address, Wad.from_number(0.000016), self.debt_auction_bid_size)
        # and
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        # and
        self.debt_auction_house.settle_auction(auction_id).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_not_instantiate_model_if_auction_is_settled(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        # and
        self.decrease_sold_amount(auction_id, self.other_address, Wad.from_number(0.000017), self.debt_auction_bid_size)
        # and
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        # and
        assert self.debt_auction_house.settle_auction(auction_id).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    def test_should_not_do_anything_if_no_output_from_model(self, auction_id):
        # given
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    def test_should_make_initial_bid(self):
        # given
        auction_id = self.debt_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_id)
        prot_before = self.geb.prot.balance_of(self.keeper_address)

        # when
        simulate_model_output(model=model, price=Wad.from_number(575.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.debt_auction_house.bids(auction_id)
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(575.0), 2)
        prot_after = self.geb.prot.balance_of(self.keeper_address)
        assert prot_before == prot_after

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_bid_even_if_there_is_already_a_bidder(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        prot_before = self.geb.prot.balance_of(self.keeper_address)
        # and
        amount_to_sell = Wad.from_number(0.000016)
        assert self.debt_auction_house.decrease_sold_amount(auction_id, amount_to_sell, self.debt_auction_bid_size).transact(from_address=self.other_address)
        assert self.debt_auction_house.bids(auction_id).amount_to_sell == amount_to_sell

        # when
        simulate_model_output(model=model, price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.debt_auction_house.bids(auction_id)
        assert auction.amount_to_sell != amount_to_sell
        assert round(auction.bid_amount / Rad(auction.amount_to_sell), 2) == round(Rad.from_number(825.0), 2)
        prot_after = self.geb.prot.balance_of(self.keeper_address)
        assert prot_before == prot_after

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_overbid_itself_if_model_has_updated_the_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(100.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert round(Rad(self.debt_auction_house.bids(auction_id).amount_to_sell), 2) == round(self.debt_auction_bid_size / Rad.from_number(100.0), 2)

        # when
        simulate_model_output(model=model, price=Wad.from_number(110.0))
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.amount_to_sell_implies_price(auction_id, Wad.from_number(110.0))

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(120.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(120.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.amount_to_sell_implies_price(auction_id, Wad.from_number(120.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(50.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        time.sleep(2)
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(60.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.amount_to_sell_implies_price(auction_id, Wad.from_number(60.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(80.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(2)
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(70.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.amount_to_sell_implies_price(auction_id, Wad.from_number(70.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_not_bid_on_rounding_errors_with_small_amounts(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(1400.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.debt_auction_house.bids(auction_id).amount_to_sell == Wad(self.debt_auction_bid_size / Rad.from_number(1400.0))

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_settle_when_we_won_the_auction(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.amount_to_sell_implies_price(auction_id, Wad.from_number(825.0))
        prot_before = self.geb.prot.balance_of(self.keeper_address)

        # when
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        prot_after = self.geb.prot.balance_of(self.keeper_address)
        assert prot_before < prot_after

    def test_should_not_settle_when_auction_finished_but_somebody_else_won(self, auction_id):
        # given
        prot_before = self.geb.prot.balance_of(self.keeper_address)
        # and
        self.decrease_sold_amount(auction_id, self.other_address, Wad.from_number(0.000015), self.debt_auction_bid_size)
        assert self.debt_auction_house.bids(auction_id).amount_to_sell == Wad.from_number(0.000015)

        # when
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        prot_after = self.geb.prot.balance_of(self.keeper_address)
        assert prot_before == prot_after

    def test_should_obey_gas_price_provided_by_the_model(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(800.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.debt_auction_house.bids(auction_id).high_bidder == self.keeper_address
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(850.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.debt_auction_house.bids(auction_id).high_bidder == self.keeper_address
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    def test_should_change_gas_strategy_when_model_output_changes(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        first_bid = Wad.from_number(90)
        simulate_model_output(model=model, price=first_bid, gas_price=2000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 2000

        # when
        second_bid = Wad.from_number(100)
        simulate_model_output(model=model, price=second_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert round(Rad(self.debt_auction_house.bids(auction_id).amount_to_sell), 2) == round(self.debt_auction_bid_size / Rad(second_bid), 2)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # when
        third_bid = Wad.from_number(110)
        new_gas_price = int(self.default_gas_price*1.25)
        simulate_model_output(model=model, price=third_bid, gas_price=new_gas_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert round(Rad(self.debt_auction_house.bids(auction_id).amount_to_sell), 2) == round(self.debt_auction_bid_size / Rad(third_bid), 2)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == new_gas_price

        # cleanup
        time_travel_by(self.web3, self.debt_auction_house.bid_duration() + 1)
        assert self.debt_auction_house.settle_auction(auction_id).transact()

    @classmethod
    def teardown_class(cls):
        cls.cleanup_debt(web3(), geb(web3()), other_address(web3()))

    @classmethod
    def cleanup_debt(cls, web3, geb, address):
        # Cancel out surplus and debt
        system_coin_accounting_engine = geb.safe_engine.coin_balance(geb.accounting_engine.address)
        assert system_coin_accounting_engine <= geb.accounting_engine.unqueued_unauctioned_debt()
        assert geb.accounting_engine.settle_debt(system_coin_accounting_engine).transact()


class MockDebtAuctionHouse:
    bid_amount = Rad.from_number(50000)
    debt_auction_bid_size = Wad.from_number(50000)

    def __init__(self):
        self.total_auction_length = 259200
        self.bid_duration = 21600
        self.amount_to_sell = self.debt_auction_bid_size
        pass

    def bids(self, id: int):
        return DebtAuctionHouse.Bid(id=id,
                           bid_amount=self.bid_amount,
                           amount_to_sell=self.amount_to_sell,
                           high_bidder=Address("0x0000000000000000000000000000000000000000"),
                           bid_expiry=0,
                           auction_deadline=int(datetime.now(tz=timezone.utc).timestamp()) + self.total_auction_length)


class TestDebtAuctionStrategy:
    def setup_class(self):
        self.geb = geb(web3())
        self.strategy = DebtAuctionStrategy(self.geb.debt_auction_house)
        self.mock_debt_auction_house = MockDebtAuctionHouse()

    def test_price(self, mocker):
        mocker.patch("pyflex.auctions.DebtAuctionHouse.bids", return_value=self.mock_debt_auction_house.bids(1))
        mocker.patch("pyflex.auctions.DebtAuctionHouse.decrease_sold_amount", return_value="tx goes here")
        model_price = Wad.from_number(190.0)
        (price, tx, bid_amount) = self.strategy.bid(1, model_price)
        assert price == model_price
        assert bid_amount == MockDebtAuctionHouse.bid_amount
        amount_to_sell1 = MockDebtAuctionHouse.debt_auction_bid_size / model_price
        DebtAuctionHouse.decrease_sold_amount.assert_called_once_with(1, amount_to_sell1, MockDebtAuctionHouse.bid_amount)

        # When bid price increases, amount_to_sell should decrease
        model_price = Wad.from_number(200.0)
        (price, tx, bid) = self.strategy.bid(1, model_price)
        amount_to_sell2 = DebtAuctionHouse.decrease_sold_amount.call_args[0][1]
        assert amount_to_sell2 < amount_to_sell1
        assert amount_to_sell2 == MockDebtAuctionHouse.debt_auction_bid_size / model_price
