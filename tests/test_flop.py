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

from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pymaker.approval import hope_directly
from pymaker.deployment import DssDeployment
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import bite, create_unsafe_cdp, flog_and_heal, gal_address, keeper_address, mcd, \
    models, our_address, other_address, reserve_dai, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from web3 import Web3


wad_maxvalue = Wad(115792089237316195423570985008687907853269984665640564039457584007913129639935)


@pytest.fixture()
def kick(web3: Web3, mcd: DssDeployment, gal_address, other_address) -> int:
    joy = mcd.vat.dai(mcd.vow.address)
    woe = (mcd.vat.sin(mcd.vow.address) - mcd.vow.sin()) - mcd.vow.ash()
    print(f'joy={str(joy)[:6]}, woe={str(woe)[:6]}')

    if woe < joy:
        # Bite gal CDP
        c = mcd.collaterals['ETH-B']
        unsafe_cdp = create_unsafe_cdp(mcd, c, Wad.from_number(2), other_address, draw_dai=False)
        flip_kick = bite(mcd, c, unsafe_cdp)

        # Generate some Dai, bid on and win the flip auction without covering all the debt
        reserve_dai(mcd, c, gal_address, Wad.from_number(100), extra_collateral=Wad.from_number(1.1))
        c.flipper.approve(mcd.vat.address, approval_function=hope_directly(from_address=gal_address))
        current_bid = c.flipper.bids(flip_kick)
        bid = Rad.from_number(1.9)
        assert mcd.vat.dai(gal_address) > bid
        assert c.flipper.tend(flip_kick, current_bid.lot, bid).transact(from_address=gal_address)
        time_travel_by(web3, c.flipper.ttl()+1)
        assert c.flipper.deal(flip_kick).transact()

    flog_and_heal(web3, mcd, past_blocks=1200, kiss=False)

    # Kick off the flop auction
    woe = (mcd.vat.sin(mcd.vow.address) - mcd.vow.sin()) - mcd.vow.ash()
    assert mcd.vow.sump() <= woe
    assert mcd.vat.dai(mcd.vow.address) == Rad(0)
    assert mcd.vow.flop().transact(from_address=gal_address)
    return mcd.flopper.kicks()


@pytest.mark.timeout(600)
class TestAuctionKeeperFlopper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = web3()
        self.our_address = our_address(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.other_address = other_address(self.web3)
        self.gal_address = gal_address(self.web3)
        self.mcd = mcd(self.web3)
        self.flopper = self.mcd.flopper
        self.flopper.approve(self.mcd.vat.address, approval_function=hope_directly(from_address=self.keeper_address))
        self.flopper.approve(self.mcd.vat.address, approval_function=hope_directly(from_address=self.other_address))

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--type flop "
                                              f"--network testnet "
                                              f"--model ./bogus-model.sh"), web3=self.web3)
        self.keeper.approve()

        reserve_dai(self.mcd, self.mcd.collaterals['ETH-C'], self.keeper_address, Wad.from_number(200.00000))
        reserve_dai(self.mcd, self.mcd.collaterals['ETH-C'], self.other_address, Wad.from_number(200.00000))

        self.sump = self.mcd.vow.sump()  # Rad

    def lot_implies_price(self, kick: int, price: Wad) -> bool:
        return round(Rad(self.flopper.bids(kick).lot), 2) == round(self.sump / Rad(price), 2)

    def test_should_detect_flop(self, web3, c, mcd, other_address, keeper_address):
        # given a count of flop auctions
        reserve_dai(mcd, c, keeper_address, Wad.from_number(230))
        kicks = mcd.flopper.kicks()

        # and an undercollateralized CDP is bitten
        unsafe_cdp = create_unsafe_cdp(mcd, c, Wad.from_number(1), other_address, draw_dai=False)
        assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()

        # when the auction ends without debt being covered
        time_travel_by(web3, c.flipper.tau() + 1)

        # then ensure testchain is in the appropriate state
        joy = mcd.vat.dai(mcd.vow.address)
        awe = mcd.vat.sin(mcd.vow.address)
        woe = (mcd.vat.sin(mcd.vow.address) - mcd.vow.sin()) - mcd.vow.ash()
        sin = mcd.vow.sin()
        sump = mcd.vow.sump()
        wait = mcd.vow.wait()
        assert joy < awe
        assert woe + sin >= sump
        assert wait == 0

        # when
        self.keeper.check_flop()
        wait_for_other_threads()

        # then ensure another flop auction was kicked off
        assert mcd.flopper.kicks() == kicks + 1

        # clean up by letting the auction expire
        time_travel_by(web3, mcd.flopper.tau() + 1)

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
        assert status.id == kick
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid > Rad.from_number(0)
        assert status.lot == wad_maxvalue
        assert status.tab is None
        assert status.beg > Ray.from_number(1)
        assert status.guy == self.mcd.vow.address
        assert status.era > 0
        assert status.end < status.era + self.flopper.tau() + 1
        assert status.tic == 0
        assert status.price == Wad(0)

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
        assert status.id == kick
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid == last_bid.bid
        assert status.lot == Wad(last_bid.bid / Rad(price))
        assert status.tab is None
        assert status.beg > Ray.from_number(1)
        assert status.guy == self.keeper_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == price

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        lot = Wad.from_number(0.0000001)
        assert self.flopper.dent(kick, lot, self.sump).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == kick
        assert status.flipper is None
        assert status.flapper is None
        assert status.flopper == self.flopper.address
        assert status.bid == self.sump
        assert status.lot == lot
        assert status.tab is None
        assert status.beg > Ray.from_number(1)
        assert status.guy == self.other_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == Wad(self.sump / Rad(lot))

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_terminate_model_if_auction_expired_due_to_tau(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, self.flopper.tau() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.flopper.dent(kick, Wad.from_number(0.00015), self.sump).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

        # cleanup
        assert self.flopper.deal(kick).transact()

    def test_should_terminate_model_if_auction_is_dealt(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.flopper.dent(kick, Wad.from_number(0.00016), self.sump).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        # and
        self.flopper.deal(kick).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_not_instantiate_model_if_auction_is_dealt(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        # and
        assert self.flopper.dent(kick, Wad.from_number(0.00017), self.sump).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        # and
        assert self.flopper.deal(kick).transact(from_address=self.other_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_not_called()

    def test_should_not_do_anything_if_no_output_from_model(self, kick):
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
        kick = self.flopper.kicks()
        (model, model_factory) = models(self.keeper, kick)
        mkr_before = self.mcd.mkr.balance_of(self.keeper_address)

        # when
        simulate_model_output(model=model, price=Wad.from_number(575.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.flopper.bids(kick)
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(575.0), 2)
        mkr_after = self.mcd.mkr.balance_of(self.keeper_address)
        assert mkr_before == mkr_after

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_bid_even_if_there_is_already_a_bidder(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        mkr_before = self.mcd.mkr.balance_of(self.keeper_address)
        # and
        lot = Wad.from_number(0.000016)
        assert self.flopper.dent(kick, lot, self.sump).transact(from_address=self.other_address)
        assert self.flopper.bids(kick).lot == lot

        # when
        simulate_model_output(model=model, price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = self.flopper.bids(kick)
        assert auction.lot != lot
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(825.0), 2)
        mkr_after = self.mcd.mkr.balance_of(self.keeper_address)
        assert mkr_before == mkr_after

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_overbid_itself_if_model_has_updated_the_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(100.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert round(Rad(self.flopper.bids(kick).lot), 2) == round(self.sump / Rad.from_number(100.0), 2)

        # when
        simulate_model_output(model=model, price=Wad.from_number(110.0))
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.lot_implies_price(kick, Wad.from_number(110.0))

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(120.0), gas_price=10)
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
        simulate_model_output(model=model, price=Wad.from_number(120.0), gas_price=15)
        # and
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.lot_implies_price(kick, Wad.from_number(120.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

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
        assert self.lot_implies_price(kick, Wad.from_number(60.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

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
        assert self.lot_implies_price(kick, Wad.from_number(70.0))
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    def test_should_not_bid_on_rounding_errors_with_small_amounts(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(1400.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.flopper.bids(kick).lot == Wad(self.sump / Rad.from_number(1400.0))

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_deal_when_we_won_the_auction(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.lot_implies_price(kick, Wad.from_number(825.0))
        mkr_before = self.mcd.mkr.balance_of(self.keeper_address)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        mkr_after = self.mcd.mkr.balance_of(self.keeper_address)
        assert mkr_before < mkr_after

    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self, kick):
        # given
        mkr_before = self.mcd.mkr.balance_of(self.keeper_address)
        # and
        assert self.flopper.dent(kick, Wad.from_number(1.5), self.sump).transact(from_address=self.other_address)
        assert self.flopper.bids(kick).lot == Wad.from_number(1.5)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        mkr_after = self.mcd.mkr.balance_of(self.keeper_address)
        assert mkr_before == mkr_after

    def test_should_obey_gas_price_provided_by_the_model(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(800.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        kick = self.flopper.kicks()
        (model, model_factory) = models(self.keeper, kick)

        # when
        simulate_model_output(model=model, price=Wad.from_number(850.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.web3.eth.gasPrice

        # cleanup
        time_travel_by(self.web3, self.flopper.ttl() + 1)
        assert self.flopper.deal(kick).transact()

    @classmethod
    def teardown_class(cls):
        cls.cleanup_debt(web3(), mcd(web3()), other_address(web3()))

    @classmethod
    def cleanup_debt(cls, web3, mcd, address):
        # Cancel out surplus and debt
        dai_vow = mcd.vat.dai(mcd.vow.address)
        assert dai_vow <= mcd.vow.woe()
        assert mcd.vow.heal(dai_vow).transact()
