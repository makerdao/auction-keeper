# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus
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
from typing import Optional

import pytest
from mock import MagicMock
from web3 import Web3, HTTPProvider

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pymaker import Address
from pymaker.approval import directly
from pymaker.auctions import Flapper
from pymaker.numeric import Wad
from pymaker.token import DSToken
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


@pytest.mark.timeout(20)
class TestAuctionKeeperFlapper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = Web3(HTTPProvider("http://localhost:8555"))
        self.web3.eth.defaultAccount = self.web3.eth.accounts[0]
        self.keeper_address = Address(self.web3.eth.defaultAccount)
        self.gal_address = Address(self.web3.eth.accounts[1])
        self.other_address = Address(self.web3.eth.accounts[2])
        self.dai = DSToken.deploy(self.web3, 'DAI')
        self.mkr = DSToken.deploy(self.web3, 'MKR')
        self.flapper = Flapper.deploy(self.web3, self.dai.address, self.mkr.address)

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--flapper {self.flapper.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)

        self.keeper.approve()

        # So that `gal_address` can kick auctions, it must have some DAI in its account
        # and also Flapper must be approved to access it
        self.dai.mint(Wad.from_number(5000000)).transact()
        self.dai.transfer(self.gal_address, Wad.from_number(5000000)).transact()
        self.dai.approve(self.flapper.address).transact(from_address=self.gal_address)

        # So that `keeper_address` and `other_address` can bid in auctions,
        # they both need to have MKR in their accounts.
        self.mkr.mint(Wad.from_number(10000000)).transact()
        self.mkr.transfer(self.other_address, Wad.from_number(5000000)).transact()

        self.model = MagicMock()
        self.model.get_stance = MagicMock(return_value=None)
        self.model_factory = self.keeper.auctions.model_factory
        self.model_factory.create_model = MagicMock(return_value=self.model)

    def simulate_model_output(self, price: Wad, gas_price: Optional[int] = None):
        self.model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once_with(Parameters(flipper=None,
                                                                           flapper=self.flapper.address,
                                                                           flopper=None,
                                                                           id=1))
        # and
        assert self.model.send_status.call_args[0][0].id == 1
        assert self.model.send_status.call_args[0][0].flipper is None
        assert self.model.send_status.call_args[0][0].flapper == self.flapper.address
        assert self.model.send_status.call_args[0][0].flopper is None
        assert self.model.send_status.call_args[0][0].bid == Wad.from_number(10)
        assert self.model.send_status.call_args[0][0].lot == Wad.from_number(200)
        assert self.model.send_status.call_args[0][0].tab is None
        assert self.model.send_status.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.gal_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic == 0
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(20.0)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count == 1

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count > 1
        # and
        assert self.model.send_status.call_args[0][0].id == 1
        assert self.model.send_status.call_args[0][0].flipper is None
        assert self.model.send_status.call_args[0][0].flapper == self.flapper.address
        assert self.model.send_status.call_args[0][0].flopper is None
        assert self.model.send_status.call_args[0][0].bid == Wad.from_number(20)
        assert self.model.send_status.call_args[0][0].lot == Wad.from_number(200)
        assert self.model.send_status.call_args[0][0].tab is None
        assert self.model.send_status.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.keeper_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(10.0)

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count == 1

        # when
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count > 1
        # and
        assert self.model.send_status.call_args[0][0].id == 1
        assert self.model.send_status.call_args[0][0].flipper is None
        assert self.model.send_status.call_args[0][0].flapper == self.flapper.address
        assert self.model.send_status.call_args[0][0].flopper is None
        assert self.model.send_status.call_args[0][0].bid == Wad.from_number(40)
        assert self.model.send_status.call_args[0][0].lot == Wad.from_number(200)
        assert self.model.send_status.call_args[0][0].tab is None
        assert self.model.send_status.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.other_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(5.0)

    def test_should_terminate_model_if_auction_expired_due_to_tau(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, self.flapper.tau() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flapper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_is_dealt(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flapper.ttl() + 5)
        # and
        self.flapper.deal(1).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

    def test_should_not_instantiate_model_if_auction_is_dealt(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
        # and
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(40)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flapper.ttl() + 5)
        # and
        self.flapper.deal(1).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_not_called()

    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    def test_should_make_initial_bid(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flapper.bids(1)
        assert round(auction.lot / auction.bid, 2) == round(Wad.from_number(10.0), 2)
        assert self.dai.balance_of(self.keeper_address) == Wad(0)

    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
        # and
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(16)).transact(from_address=self.other_address)
        assert self.flapper.bids(1).bid == Wad.from_number(16)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flapper.bids(1)
        assert round(auction.lot / auction.bid, 2) == round(Wad.from_number(10.0), 2)
        assert self.dai.balance_of(self.keeper_address) == Wad(0)

    def test_should_overbid_itself_if_model_has_updated_the_price(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad.from_number(20.0)

        # when
        self.simulate_model_output(price=Wad.from_number(5.0))
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad.from_number(40.0)

    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(price=Wad.from_number(10.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad.from_number(20.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(price=Wad.from_number(5.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad.from_number(40.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        self.simulate_model_output(price=Wad.from_number(8.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad.from_number(25.0)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    def test_should_not_bid_on_rounding_errors_with_small_amounts(self):
        # given
        self.flapper.kick(self.gal_address, Wad(20), Wad(1)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(9.95))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flapper.bids(1).bid == Wad(2)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_deal_when_we_won_the_auction(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flapper.bids(1)
        assert round(auction.lot / auction.bid, 2) == round(Wad.from_number(10.0), 2)
        assert self.dai.balance_of(self.keeper_address) == Wad(0)

        # when
        time_travel_by(self.web3, self.flapper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.dai.balance_of(self.keeper_address) > Wad(0)

    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
        # and
        self.flapper.approve(directly(from_address=self.other_address))
        self.flapper.tend(1, Wad.from_number(200), Wad.from_number(16)).transact(from_address=self.other_address)
        assert self.flapper.bids(1).bid == Wad.from_number(16)

        # when
        time_travel_by(self.web3, self.flapper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.dai.balance_of(self.other_address) == Wad(0)

    def test_should_obey_gas_price_provided_by_the_model(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == GAS_PRICE
