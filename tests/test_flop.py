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
from typing import Optional

import pytest
from mock import MagicMock
from web3 import Web3, HTTPProvider

from auction_keeper.main import AuctionKeeper
from auction_keeper.logic import Stance
from auction_keeper.model import Parameters, Status
from datetime import datetime
from pymaker import Address, Contract
from pymaker.approval import directly, hope_directly
from pymaker.auctions import Flipper, Flopper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Urn
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import web3, wrap_eth, reserve_dai, mcd, max_dart, \
    our_address, keeper_address, other_address, gal_address, \
    create_unsafe_cdp, simulate_model_output, models
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


wad_maxvalue = Wad(115792089237316195423570985008687907853269984665640564039457584007913129639935)


@pytest.fixture()
def kick(web3: Web3, mcd: DssDeployment, gal_address, other_address) -> int:
    # Bite gal CDP
    c = mcd.collaterals[1]
    unsafe_cdp = create_unsafe_cdp(mcd, c, Wad.from_number(2), other_address)
    assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()
    flip_kick = c.flipper.kicks()
    last_bite = mcd.cat.past_bite(1)[0]

    # Generate some Dai, bid on and win the flip auction without covering all the debt
    wrap_eth(mcd, gal_address, Wad.from_number(1))
    c.approve(gal_address)
    assert c.adapter.join(gal_address, Wad.from_number(1)).transact(from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, dink=Wad.from_number(1), dart=Wad(0)).transact(
        from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, dink=Wad(0), dart=max_dart(mcd, c, gal_address)).transact(
        from_address=gal_address)
    c.flipper.approve(mcd.vat.address, approval_function=hope_directly(), from_address=gal_address)
    current_bid = c.flipper.bids(flip_kick)
    bid = Rad(237)
    assert mcd.vat.dai(gal_address) > bid
    assert c.flipper.tend(flip_kick, current_bid.lot, bid).transact(from_address=gal_address)
    time_travel_by(web3, c.flipper.ttl()+1)
    assert c.flipper.deal(flip_kick).transact()

    # Raise debt from the queue
    assert mcd.vow.flog(last_bite.era(web3)).transact(from_address=gal_address)
    # Cancel out surplus and debt
    assert bid <= mcd.vat.dai(mcd.vow.address)
    woe = (mcd.vat.sin(mcd.vow.address) - mcd.vow.sin()) - mcd.vow.ash()
    assert bid <= woe
    assert mcd.vow.heal(bid).transact()
    assert mcd.vow.flop().transact(from_address=gal_address)
    return mcd.flop.kicks()


@pytest.mark.timeout(200)
class TestAuctionKeeperFlopper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.our_address = our_address(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.other_address = other_address(self.web3)
        self.gal_address = gal_address(self.web3)
        self.mcd = mcd(self.web3, our_address, keeper_address)
        self.flopper = self.mcd.flop
        self.flopper.approve(self.mcd.vat.address, approval_function=hope_directly(), from_address=self.keeper_address)

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--flopper {self.flopper.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)
        self.keeper.approve()

        reserve_dai(self.mcd, self.mcd.collaterals[0], self.keeper_address, Wad.from_number(100.00000))
        reserve_dai(self.mcd, self.mcd.collaterals[0], self.other_address, Wad.from_number(100.00000))

        self.sump = self.mcd.vow.sump()

    # TODO: Add test which creates debt and confirms the keeper will automatically kick.

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once_with(Parameters(flipper=None,
                                                                      flapper=None,
                                                                      flopper=self.flopper.address,
                                                                      id=kick))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid == Rad.from_number(0.00001)
        assert status.lot == wad_maxvalue
        assert status.tab is None
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == self.mcd.vow.address
        assert status.era > 0
        assert status.end < status.era + self.flopper.tau() + 1
        assert status.tic == 0
        assert status.price == Wad(0)

    #@pytest.mark.skip("meddling with amounts")
    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        kick = self.flopper.kicks()
        (model, model_factory) = models(self.keeper, kick)

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
        last_bid = self.flopper.bids(kick)
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid == last_bid.bid
        assert status.lot == Wad(last_bid.bid / Rad(price))
        assert status.tab is None
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == self.keeper_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == price

    #@pytest.mark.skip("meddling with amounts")
    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self):
        # given
        kick = self.flopper.kicks()
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        self.flopper.approve(self.mcd.vat.address, approval_function=hope_directly(), from_address=self.other_address)
        lot = Wad.from_number(0.0000001)
        assert self.flopper.dent(kick, lot, self.sump).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid == self.sump
        assert status.lot == lot
        assert status.tab is None
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == self.other_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == Wad(self.sump / Rad(lot))

    @pytest.mark.skip()
    def test_should_terminate_model_if_auction_expired_due_to_tau(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, self.flopper.tau() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip()
    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip()
    def test_should_terminate_model_if_auction_is_dealt(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.flopper.deal(1).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    @pytest.mark.skip()
    def test_should_not_instantiate_model_if_auction_is_dealt(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.flopper.deal(1).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    @pytest.mark.skip()
    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    @pytest.mark.skip()
    def test_should_make_initial_bid(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

    @pytest.mark.skip()
    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        assert self.flopper.bids(1).lot == Wad.from_number(1.5)

        # when
        simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

    @pytest.mark.skip()
    def test_should_overbid_itself_if_model_has_updated_the_price(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(100.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.1)

        # when
        simulate_model_output(price=Wad.from_number(200.0))
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.05)

    @pytest.mark.skip()
    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(100.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(price=Wad.from_number(100.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.1)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip()
    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(100.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(price=Wad.from_number(200.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.05)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip()
    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(100.0), gas_price=10)
        # and
        self.start_ignoring_transactions()
        # and
        self.keeper.check_all_auctions()
        # and
        time.sleep(5)
        # and
        self.end_ignoring_transactions()
        # and
        simulate_model_output(price=Wad.from_number(50.0), gas_price=15)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.2)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

    @pytest.mark.skip()
    def test_should_not_bid_on_rounding_errors_with_small_amounts(self):
        # given
        self.flopper.kick(self.gal_address, Wad(10), Wad(10000)).transact()

        # when
        simulate_model_output(price=Wad.from_number(1400.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(1).lot == Wad(7)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    @pytest.mark.skip()
    def test_should_deal_when_we_won_the_auction(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.mkr.balance_of(self.keeper_address) > Wad(0)

    @pytest.mark.skip()
    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        assert self.flopper.bids(1).lot == Wad.from_number(1.5)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.mkr.balance_of(self.other_address) == Wad(0)

    @pytest.mark.skip()
    def test_should_obey_gas_price_provided_by_the_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(825.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    @pytest.mark.skip()
    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == self.web3.eth.gasPrice
