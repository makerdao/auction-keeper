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
import threading
import math
import pytest

from auction_keeper.gas import DynamicGasPrice
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pyflex.approval import directly, approve_safe_modification_directly
from pyflex.gf import Collateral
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import c, geb, mint_prot, reserve_system_coin, set_collateral_price, web3, \
    our_address, keeper_address, other_address, auction_income_recipient_address, get_node_gas_price, \
    max_delta_debt, is_safe_safe, liquidate, create_safe_with_surplus, simulate_model_output, models, set_collateral_price
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest

@pytest.fixture()
def auction_id(geb, c: Collateral, auction_income_recipient_address) -> int:

    set_collateral_price(geb, c, Wad.from_number(200))
    create_safe_with_surplus(geb, c, auction_income_recipient_address)

    assert geb.accounting_engine.auction_surplus().transact(from_address=auction_income_recipient_address)
    auction_id = geb.surplus_auction_house.auctions_started()
    assert auction_id > 0

    current_bid = geb.surplus_auction_house.bids(auction_id)
    assert current_bid.amount_to_sell == geb.accounting_engine.surplus_auction_amount_to_sell()
    return auction_id


@pytest.mark.timeout(380)
class TestAuctionKeeperSurplus(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.our_address = our_address(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.other_address = other_address(self.web3)
        self.auction_income_recipient_address = auction_income_recipient_address(self.web3)
        self.geb = geb(self.web3)
        self.surplus_auction_house = self.geb.surplus_auction_house
        self.surplus_auction_house.approve(self.geb.prot.address, directly(from_address=self.other_address))
        #self.min_auction = self.geb.surplus_auction_house.auctions_started() + 1

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--type surplus "
                                              f"--from-block 1 "
                                              #f"--min-auction {self.min_auction} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)
        self.keeper.approve()

        mint_prot(self.geb.prot, self.keeper_address, Wad.from_number(50000))
        mint_prot(self.geb.prot, self.other_address, Wad.from_number(50000))

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        # Since no args were assigned, gas strategy should return a GeometricGasPrice starting at the node gas price
        self.default_gas_price = get_node_gas_price(self.web3)

    #@pytest.mark.skip("tmp")
    def test_should_detect_surplus_auction(self, web3, geb, c, auction_income_recipient_address, keeper_address):

        print(self.keeper)
        # given some PROT is available to the keeper and a count of surplus auctions
        mint_prot(geb.prot, keeper_address, Wad.from_number(50000))
        auctions_started = geb.surplus_auction_house.auctions_started()

        # when surplus is generated
        create_safe_with_surplus(geb, c, auction_income_recipient_address)
        self.keeper.check_surplus()
        for thread in threading.enumerate():
            print(thread)
        wait_for_other_threads()

        # then ensure another surplus auction was started
        auction_id = geb.surplus_auction_house.auctions_started()
        assert auction_id == auctions_started + 1

        # clean up by letting someone else bid and waiting until the auction ends
        auction = self.surplus_auction_house.bids(auction_id)
        assert self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(30)).transact(from_address=self.other_address)
        time_travel_by(web3, geb.surplus_auction_house.bid_duration() + 1)

    #@pytest.mark.skip("tmp")
    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_start(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once_with(Parameters(collateral_auction_house=None,
                                                                      surplus_auction_house=self.surplus_auction_house.address,
                                                                      debt_auction_house=None,
                                                                      id=auction_id))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house == self.surplus_auction_house.address
        assert status.debt_auction_house is None
        assert status.bid_amount == Wad(0)
        assert status.amount_to_sell == self.geb.accounting_engine.surplus_auction_amount_to_sell()
        assert status.amount_to_raise is None
        assert status.bid_increase == self.geb.surplus_auction_house.bid_increase()
        assert status.high_bidder == self.geb.accounting_engine.address
        assert status.block_time > 0
        assert status.auction_deadline < status.block_time + self.surplus_auction_house.total_auction_length() + 1
        assert status.bid_expiry == 0
        assert status.price is None

    #@pytest.mark.skip("tmp")
    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        auction_id = self.surplus_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        simulate_model_output(model=model, price=Wad.from_number(9))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house == self.surplus_auction_house.address
        assert status.debt_auction_house is None
        assert status.bid_amount == Wad(self.surplus_auction_house.bids(auction_id).amount_to_sell / Rad.from_number(9))
        assert status.amount_to_sell == self.geb.accounting_engine.surplus_auction_amount_to_sell()
        assert status.amount_to_raise is None
        assert status.bid_increase == self.geb.surplus_auction_house.bid_increase()
        assert status.high_bidder == self.keeper_address
        assert status.block_time > 0
        assert status.auction_deadline > status.block_time
        assert status.bid_expiry > status.block_time
        assert round(status.price, 2) == round(Wad.from_number(9), 2)

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        auction = self.surplus_auction_house.bids(auction_id)
        assert Wad.from_number(40) > auction.bid_amount
        assert self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        auction = self.surplus_auction_house.bids(auction_id)
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == auction_id
        assert status.collateral_auction_house is None
        assert status.surplus_auction_house == self.surplus_auction_house.address
        assert status.debt_auction_house is None
        assert status.bid_amount == Wad.from_number(40)
        assert status.amount_to_sell == auction.amount_to_sell
        assert status.amount_to_raise is None
        assert status.bid_increase == self.geb.surplus_auction_house.bid_increase()
        assert status.high_bidder == self.other_address
        assert status.block_time > 0
        assert status.auction_deadline > status.block_time
        assert status.bid_expiry > status.block_time
        assert status.price == Wad(auction.amount_to_sell / Rad(auction.bid_amount))

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
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
        time_travel_by(self.web3, self.surplus_auction_house.total_auction_length() + 1)
        # and
        simulate_model_output(model=model, price=Wad.from_number(9.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        model.terminate.assert_not_called()
        auction = self.surplus_auction_house.bids(auction_id)
        assert round(Wad(auction.amount_to_sell) / auction.bid_amount, 2) == round(Wad.from_number(9.0), 2)

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        model_factory.create_model.assert_called_once()
        self.keeper.check_all_auctions()
        model.terminate.assert_called_once()

    #@pytest.mark.skip("tmp")
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
        auction = self.surplus_auction_house.bids(auction_id)
        assert self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    #@pytest.mark.skip("tmp")
    def test_should_terminate_model_if_auction_is_settled(self, auction_id):
        # given
        auction_id = self.surplus_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        auction = self.surplus_auction_house.bids(auction_id)
        assert self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        # and
        assert self.surplus_auction_house.settle_auction(auction_id).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    #@pytest.mark.skip("tmp")
    def test_should_not_instantiate_model_if_auction_is_settled(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        # and
        auction = self.surplus_auction_house.bids(auction_id)
        self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        # and
        self.surplus_auction_house.settle_auction(auction_id).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    #@pytest.mark.skip("tmp")
    def test_should_not_do_anything_if_no_output_from_model(self, auction_id):
        # given
        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    #@pytest.mark.skip("tmp")
    def test_should_make_initial_bid(self):
        # given
        auction_id = self.surplus_auction_house.auctions_started()
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.surplus_auction_house.bids(auction_id)
        assert round(Wad(auction.amount_to_sell) / auction.bid_amount, 2) == round(Wad.from_number(10.0), 2)

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_bid_even_if_there_is_already_a_bidder(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        # and
        auction = self.surplus_auction_house.bids(auction_id)
        assert self.surplus_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, Wad.from_number(16)).transact(from_address=self.other_address)
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad.from_number(16)

        # when
        simulate_model_output(model=model, price=Wad.from_number(0.0000005))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.surplus_auction_house.bids(auction_id)
        assert round(Wad(auction.amount_to_sell) / auction.bid_amount, 2) == round(Wad.from_number(0.0000005), 2)

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_overbid_itself_if_model_has_updated_the_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        first_bid = Wad.from_number(0.0000004)
        simulate_model_output(model=model, price=first_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell / Rad(first_bid))

        # when
        second_bid = Wad.from_number(0.0000003)
        simulate_model_output(model=model, price=second_bid)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell / Rad(second_bid))

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        simulate_model_output(model=model, price=Wad.from_number(10.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(10.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell) / Wad.from_number(10.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        simulate_model_output(model=model, price=Wad.from_number(9.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(8.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert round(self.surplus_auction_house.bids(auction_id).bid_amount, 2) == round(Wad(amount_to_sell / Rad.from_number(8.0)), 2)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        simulate_model_output(model=model, price=Wad.from_number(10.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(model=model, price=Wad.from_number(8.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell) / Wad.from_number(8.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_not_bid_on_rounding_errors_with_small_amounts(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        price = Wad.from_number(9.0)-Wad(5)
        simulate_model_output(model=model, price=price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell) / Wad(price)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_settle_when_we_won_the_auction(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(8.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.surplus_auction_house.bids(auction_id)
        assert auction.bid_amount > Wad(0)
        assert round(Wad(auction.amount_to_sell) / auction.bid_amount, 2) == round(Wad.from_number(8.0), 2)
        system_coin_before = self.geb.safe_engine.coin_balance(self.keeper_address)

        # when
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        system_coin_after = self.geb.safe_engine.coin_balance(self.keeper_address)
        # then
        assert system_coin_before < system_coin_after

    #@pytest.mark.skip("tmp")
    def test_should_not_settle_when_auction_finished_but_somebody_else_won(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell
        # and
        assert self.surplus_auction_house.increase_bid_size(auction_id, amount_to_sell, Wad.from_number(16)).transact(from_address=self.other_address)
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad.from_number(16)

        # when
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad.from_number(16)

    #@pytest.mark.skip("tmp")
    def test_should_obey_gas_price_provided_by_the_model(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(10.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_use_default_gas_price_if_not_provided_by_the_model(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)

        # when
        simulate_model_output(model=model, price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.surplus_auction_house.bids(auction_id)
        assert auction.high_bidder == self.keeper_address
        assert auction.bid_amount > Wad(0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        print(f"tx gas price is {self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice}, web3.eth.gasPrice is {self.web3.eth.gasPrice}")

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    #@pytest.mark.skip("tmp")
    def test_should_change_gas_strategy_when_model_output_changes(self, auction_id):
        # given
        (model, model_factory) = models(self.keeper, auction_id)
        amount_to_sell = self.surplus_auction_house.bids(auction_id).amount_to_sell

        # when
        first_bid = Wad.from_number(0.0000009)
        simulate_model_output(model=model, price=first_bid, gas_price=2000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 2000

        # when
        second_bid = Wad.from_number(0.0000006)
        simulate_model_output(model=model, price=second_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell / Rad(second_bid))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # when
        third_bid = Wad.from_number(0.0000003)
        new_gas_price = int(self.default_gas_price*1.25)
        simulate_model_output(model=model, price=third_bid, gas_price=new_gas_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.surplus_auction_house.bids(auction_id).bid_amount == Wad(amount_to_sell / Rad(third_bid))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == new_gas_price

        # cleanup
        time_travel_by(self.web3, self.surplus_auction_house.bid_duration() + 1)
        assert self.surplus_auction_house.settle_auction(auction_id).transact()

    @classmethod
    def teardown_class(cls):
        cls.geb = geb(web3())
        #cls.liquidate_safe(web3(), cls.geb, c(cls.geb), auction_income_recipient_address(web3()), our_address(web3()))

    @classmethod
    def liquidate_safe(cls, web3, geb, c, auction_income_recipient_address, our_address):
        safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)

        delta_debt = max_delta_debt(geb, c, auction_income_recipient_address) - Wad.from_number(1)
        assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, auction_income_recipient_address, Wad(0), delta_debt).transact(from_address=auction_income_recipient_address)
        safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
        set_collateral_price(geb, c, Wad.from_number(10))

        # Ensure the SAFE isn't safe
        assert not is_safe_safe(geb.safe_engine.collateral_type(c.collateral_type.name), safe)

        # Determine how many liquidations will be required
        liquidation_quantity = Wad(geb.liquidation_engine.liquidation_quantity(c.collateral_type))
        liquidations_required = math.ceil(safe.generated_debt / liquidation_quantity)
        print(f"locked_collateral={safe.locked_collateral} generated_debt={safe.generated_debt} so {liquidations_required} liquidations are required")
        c.collateral_auction_house.approve(geb.safe_engine.address, approval_function=approve_safe_modification_directly(from_address=our_address))

        # First auction that will be started
        first_auction_id = c.collateral_auction_house.auctions_started() + 1

        # liquidate and bid on each auction
        for _ in range(liquidations_required):
            auction_id = liquidate(geb, c, safe)
            assert auction_id > 0
            auction = c.collateral_auction_house.bids(auction_id)
            bid_amount = Wad(auction.amount_to_raise) + Wad(1)
            reserve_system_coin(geb, c, our_address, bid_amount)
            assert c.collateral_auction_house.increase_bid_size(auction_id, auction.amount_to_sell, auction.amount_to_raise).transact(from_address=our_address)

        time_travel_by(web3, c.collateral_auction_house.total_auction_length()+1)
        for auction_id in range(first_auction_id, c.collateral_auction_house.auctions_started()+1):
            assert c.collateral_auction_house.settle_auction(auction_id).transact()

        set_collateral_price(geb, c, Wad.from_number(200))
        safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
        #assert safe.locked_collateral == Wad(0)
        #assert safe.generated_debt == Wad(0)
