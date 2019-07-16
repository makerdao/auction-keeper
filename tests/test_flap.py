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

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pymaker import Address
from pymaker.approval import directly
from pymaker.auctions import Flapper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Ilk, Urn
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSToken
from tests.conftest import web3, wrap_eth, mcd, our_address, keeper_address, gal_address, \
    simulate_model_output, models
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


def create_cdp_with_surplus(mcd: DssDeployment, c: Collateral, gal_address: Address) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    collateral_amount = Wad.from_number(1)
    wrap_eth(mcd, gal_address, collateral_amount)
    c.approve(gal_address)
    assert c.adapter.join(gal_address, collateral_amount).transact(
        from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, dink=collateral_amount, dart=Wad.from_number(100)).transact(
        from_address=gal_address)
    assert mcd.vat.dai(mcd.vow.address) == Rad(0)
    assert mcd.jug.drip(c.ilk).transact(from_address=gal_address)
    # total surplus > total debt + surplus auction lot size + surplus buffer
    assert mcd.vat.dai(mcd.vow.address) > mcd.vat.sin(mcd.vow.address) + mcd.vow.bump() + mcd.vow.hump()
    return mcd.vat.urn(c.ilk, gal_address)


@pytest.fixture()
def kick(mcd, c: Collateral, gal_address) -> int:
    print(f'debt before={str(mcd.vat.debt())}')
    urn = create_cdp_with_surplus(mcd, c, gal_address)
    print(f'urn={urn}')
    print(f'debt after={str(mcd.vat.debt())}')

    assert mcd.vow.flap().transact(from_address=gal_address)
    kick = mcd.flap.kicks()
    assert kick > 0

    current_bid = mcd.flap.bids(kick)
    assert current_bid.lot > Rad(0)

    return kick


@pytest.mark.timeout(20)
class TestAuctionKeeperFlapper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.our_address = our_address(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.gal_address = gal_address(self.web3)
        self.mcd = mcd(self.web3, our_address, keeper_address)
        self.flapper = self.mcd.flap

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--mkr {self.mcd.mkr.address} "
                                              f"--flapper {self.mcd.flap.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)

        self.keeper.approve()

        # # So that `gal_address` can kick auctions, it must have some DAI in its account
        # # and also Flapper must be approved to access it
        # self.dai.mint(Wad.from_number(5000000)).transact()
        # self.dai.transfer(self.gal_address, Wad.from_number(5000000)).transact()
        # self.dai.approve(self.flapper.address).transact(from_address=self.gal_address)
        #
        # # So that `keeper_address` and `other_address` can bid in auctions,
        # # they both need to have MKR in their accounts.
        # self.mkr.mint(Wad.from_number(10000000)).transact()
        # self.mkr.transfer(self.other_address, Wad.from_number(5000000)).transact()

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, kick: int):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once_with(Parameters(flipper=None,
                                                                      flapper=self.flapper.address,
                                                                      flopper=None,
                                                                      id=kick))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == 1
        assert status.flipper is None
        assert status.flapper == self.flapper.address
        assert status.flopper is None
        assert status.bid == Wad(0)
        assert status.lot == self.mcd.vow.bump()
        assert status.tab is None
        assert status.beg == Ray.from_number(1.05)
        assert status.guy == self.mcd.vow.address
        assert status.era > 0
        assert status.end < status.era + self.flapper.tau() + 1
        assert status.tic == 0
        assert status.price is None

    @pytest.mark.skip("Needs updating")
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
        assert self.model.send_status.call_args[0][0].beg == Ray.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.keeper_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(10.0)

    @pytest.mark.skip("Needs updating")
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
        assert self.model.send_status.call_args[0][0].beg == Ray.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.other_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(5.0)

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
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

    @pytest.mark.skip("Needs updating")
    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        self.flapper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(10.0))
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == self.web3.eth.gasPrice
