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
from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.auctions import Flipper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import bite, create_unsafe_cdp, flog_and_heal, keeper_address, mcd, models, \
                           reserve_dai, simulate_model_output, web3
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest
from typing import Optional


tend_lot = Wad.from_number(1.2)
tend_small_lot = Wad(2000)


@pytest.fixture()
def kick(mcd, c: Collateral, gal_address) -> int:
    # Ensure we start with a clean urn
    urn = mcd.vat.urn(c.ilk, gal_address)
    assert urn.ink == Wad(0)
    assert urn.art == Wad(0)

    # Bite gal CDP
    unsafe_cdp = create_unsafe_cdp(mcd, c, tend_lot, gal_address)
    return bite(mcd, c, unsafe_cdp)


@pytest.fixture()
def kick_small_lot(mcd, c: Collateral, gal_address) -> int:
    unsafe_cdp = create_unsafe_cdp(mcd, c, tend_small_lot, gal_address)
    return bite(mcd, c, unsafe_cdp)


@pytest.mark.timeout(500)
class TestAuctionKeeperFlipper(TransactionIgnoringTest):
    def setup_class(self):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        self.web3 = web3()
        self.mcd = mcd(self.web3)
        self.keeper_address = keeper_address(self.web3)
        self.collateral = self.mcd.collaterals['ETH-B']
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address.address} "
                                     f"--type flip "
                                     f"--from-block 1 "
                                     f"--ilk {self.collateral.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=self.mcd.web3)
        self.keeper.approve()

        assert isinstance(self.keeper.gas_price, DynamicGasPrice)
        self.default_gas_price = self.keeper.gas_price.get_gas_price(0)

    @staticmethod
    def gem_balance(address: Address, c: Collateral) -> Wad:
        assert (isinstance(address, Address))
        assert (isinstance(c, Collateral))
        return Wad(c.gem.balance_of(address))

    def simulate_model_bid(self, mcd: DssDeployment, c: Collateral, model: object,
                           price: Wad, gas_price: Optional[int] = None):
        assert (isinstance(mcd, DssDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(price, Wad))
        assert (isinstance(gas_price, int)) or gas_price is None
        assert price > Wad(0)

        flipper = c.flipper
        initial_bid = flipper.bids(model.id)
        assert initial_bid.lot > Wad(0)
        our_bid = price * initial_bid.lot
        reserve_dai(mcd, c, self.keeper_address, our_bid, extra_collateral=Wad.from_number(2))
        simulate_model_output(model=model, price=price, gas_price=gas_price)

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
        assert flipper.beg() * lot <= current_bid.lot

        assert flipper.dent(id, lot, bid).transact(from_address=address)

    @staticmethod
    def tend_with_dai(mcd: DssDeployment, c: Collateral, flipper: Flipper, id: int, address: Address, bid: Rad):
        assert (isinstance(mcd, DssDeployment))
        assert (isinstance(c, Collateral))
        assert (isinstance(flipper, Flipper))
        assert (isinstance(id, int))
        assert (isinstance(bid, Rad))

        flipper.approve(flipper.vat(), approval_function=hope_directly(from_address=address))
        previous_bid = flipper.bids(id)
        c.approve(address)
        reserve_dai(mcd, c, address, Wad(bid), extra_collateral=Wad.from_number(2))
        TestAuctionKeeperFlipper.tend(flipper, id, address, previous_bid.lot, bid)

    def test_flipper_address(self):
        """ Sanity check ensures the keeper fixture is looking at the correct collateral """
        assert self.keeper.flipper.address == self.collateral.flipper.address

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        initial_bid = self.collateral.flipper.bids(kick)
        # then
        model_factory.create_model.assert_called_once_with(Parameters(flipper=self.collateral.flipper.address,
                                                                      flapper=None,
                                                                      flopper=None,
                                                                      id=kick))
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == kick
        assert status.flipper == self.collateral.flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == Rad.from_number(0)
        assert status.lot == initial_bid.lot
        assert status.tab == initial_bid.tab
        assert status.beg > Wad.from_number(1)
        assert status.guy == self.mcd.cat.address
        assert status.era > 0
        assert status.end < status.era + self.collateral.flipper.tau() + 1
        assert status.tic == 0
        assert status.price == Wad(0)

        # cleanup
        time_travel_by(self.web3, self.collateral.flipper.ttl() + 1)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self, kick):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        previous_bid = flipper.bids(model.id)
        # then
        assert model.send_status.call_count == 1

        # when
        initial_bid = flipper.bids(kick)
        our_price = Wad.from_number(30)
        our_bid = our_price * initial_bid.lot
        reserve_dai(self.mcd, self.collateral, self.keeper_address, our_bid)
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
        assert status.id == kick
        assert status.flipper == flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == Rad(our_price * status.lot)
        assert status.lot == previous_bid.lot
        assert status.tab == previous_bid.tab
        assert status.beg > Wad.from_number(1)
        assert status.guy == self.keeper_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == our_price

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self, kick, other_address):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count == 1

        # when
        flipper.approve(flipper.vat(), approval_function=hope_directly(from_address=other_address))
        previous_bid = flipper.bids(kick)
        new_bid_amount = Rad.from_number(80)
        self.tend_with_dai(self.mcd, self.collateral, flipper, model.id, other_address, new_bid_amount)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert model.send_status.call_count > 1
        # and
        status = model.send_status.call_args[0][0]
        assert status.id == kick
        assert status.flipper == flipper.address
        assert status.flapper is None
        assert status.flopper is None
        assert status.bid == new_bid_amount
        assert status.lot == previous_bid.lot
        assert status.tab == previous_bid.tab
        assert status.beg > Wad.from_number(1)
        assert status.guy == other_address
        assert status.era > 0
        assert status.end > status.era
        assert status.tic > status.era
        assert status.price == (Wad(new_bid_amount) / previous_bid.lot)

    def test_should_terminate_model_if_auction_expired_due_to_tau(self, kick):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, flipper.tau() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self, kick, other_address):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        flipper.approve(flipper.vat(), approval_function=hope_directly(from_address=other_address))
        new_bid_amount = Rad.from_number(85)
        self.tend_with_dai(self.mcd, self.collateral, flipper, kick, other_address, new_bid_amount)
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

        # cleanup
        assert flipper.deal(kick).transact()

    def test_should_terminate_model_if_auction_is_dealt(self, kick, other_address):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_not_called()

        # when
        self.tend_with_dai(self.mcd, self.collateral, flipper, kick, other_address, Rad.from_number(90))
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        flipper.deal(kick).transact(from_address=other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once()
        model.terminate.assert_called_once()

    def test_should_not_instantiate_model_if_auction_is_dealt(self, kick, other_address):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper
        # and
        TestAuctionKeeperFlipper.tend_with_dai(self.mcd, self.collateral, flipper, kick, other_address,
                                               Rad.from_number(90))
        # and
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        flipper.deal(kick).transact(from_address=other_address)

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

    def test_should_make_initial_bid(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        self.simulate_model_bid(self.mcd, self.collateral, model, Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(16.0), 2)

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_bid_even_if_there_is_already_a_bidder(self, kick, other_address):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper
        # and
        self.tend_with_dai(self.mcd, self.collateral, flipper, kick, other_address, Rad.from_number(21))
        assert flipper.bids(kick).bid == Rad.from_number(21)

        # when
        self.simulate_model_bid(self.mcd, self.collateral, model, Wad.from_number(23))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad.from_number(23), 2)

    def test_should_sequentially_tend_and_dent_if_price_takes_us_to_the_dent_phrase(self, kick, keeper_address):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        our_bid_price = Wad.from_number(150)
        assert our_bid_price * flipper.bids(kick).lot > Wad(flipper.bids(1).tab)

        self.simulate_model_bid(self.mcd, self.collateral, model, our_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        reserve_dai(self.mcd, self.collateral, keeper_address, Wad(auction.tab))
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot < tend_lot
        assert round(auction.bid / Rad(auction.lot), 2) == round(Rad(our_bid_price), 2)

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_use_most_up_to_date_price_for_dent_even_if_it_gets_updated_during_tend(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        first_bid_price = Wad.from_number(140)
        self.simulate_model_bid(self.mcd, self.collateral, model, first_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        second_bid_price = Wad.from_number(150)
        self.simulate_model_bid(self.mcd, self.collateral, model, second_bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == Wad(auction.bid / Rad(second_bid_price))

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_only_tend_if_bid_is_only_slightly_above_tab(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        auction = flipper.bids(kick)
        bid_price = Wad(auction.tab) + Wad.from_number(0.1)
        self.simulate_model_bid(self.mcd, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_tend_up_to_exactly_tab_if_bid_is_only_slightly_below_tab(self, kick):
        """I assume the point of this test is that the bid increment should be ignored when `tend`ing the `tab`
        to transition the auction into _dent_ phase."""
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        auction = flipper.bids(kick)
        assert auction.bid == Rad(0)
        bid_price = Wad(auction.tab / Rad(tend_lot)) - Wad.from_number(0.01)
        self.simulate_model_bid(self.mcd, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid < auction.tab
        assert round(auction.bid, 2) == round(Rad(bid_price * tend_lot), 2)
        assert auction.lot == tend_lot

        # when
        price_to_reach_tab = Wad(auction.tab / Rad(tend_lot)) + Wad(1)
        self.simulate_model_bid(self.mcd, self.collateral, model, price_to_reach_tab)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        auction = flipper.bids(kick)
        assert auction.bid == auction.tab
        assert auction.lot == tend_lot

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_overbid_itself_if_model_has_updated_the_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        first_bid = Wad.from_number(15.0)
        self.simulate_model_bid(self.mcd, self.collateral, model, first_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick).bid == Rad(first_bid * tend_lot)

        # when
        second_bid = Wad.from_number(20.0)
        self.simulate_model_bid(self.mcd, self.collateral, model, second_bid)
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick).bid == Rad(second_bid * tend_lot)

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_increase_gas_price_of_pending_transactions_if_model_increases_gas_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        bid_price = Wad.from_number(20.0)
        reserve_dai(self.mcd, self.collateral, self.keeper_address, bid_price * tend_lot * 2)
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
        assert flipper.bids(kick).bid == Rad(bid_price * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_replace_pending_transactions_if_model_raises_bid_and_increases_gas_price(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper

        # when
        reserve_dai(self.mcd, self.collateral, self.keeper_address, Wad.from_number(35.0) * tend_lot * 2)
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
        assert flipper.bids(kick).bid == Rad(Wad.from_number(20.0) * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_replace_pending_transactions_if_model_lowers_bid_and_increases_gas_price(self, kick):
        """ Assuming we want all bids to be submitted as soon as output from the model is parsed,
        this test seems impractical.  In real applications, the model would be unable to submit a lower bid. """
        # given
        (model, model_factory) = models(self.keeper, kick)
        flipper = self.collateral.flipper
        assert self.mcd.web3 == self.web3

        # when
        bid_price = Wad.from_number(20.0)
        reserve_dai(self.mcd, self.collateral, self.keeper_address, bid_price * tend_lot)
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
        assert flipper.bids(kick).bid == Rad(Wad.from_number(15.0) * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 15

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_not_tend_on_rounding_errors_with_small_amounts(self, kick_small_lot):
        # given
        (model, model_factory) = models(self.keeper, kick_small_lot)
        flipper = self.collateral.flipper

        # when
        bid_price = Wad.from_number(3.0)
        self.simulate_model_bid(self.mcd, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick_small_lot).bid == Rad(bid_price * tend_small_lot)

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_not_dent_on_rounding_errors_with_small_amounts(self):
        # given
        flipper = self.collateral.flipper
        kick_small_lot = flipper.kicks()
        (model, model_factory) = models(self.keeper, kick_small_lot)

        # when
        auction = flipper.bids(kick_small_lot)
        bid_price = Wad(auction.tab / Rad(tend_small_lot))
        self.simulate_model_bid(self.mcd, self.collateral, model, bid_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick_small_lot).lot == auction.lot

        # when
        tx_count = self.web3.eth.getTransactionCount(self.keeper_address.address)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getTransactionCount(self.keeper_address.address) == tx_count

    def test_should_deal_when_we_won_the_auction(self):
        # given
        flipper = self.collateral.flipper
        kick = flipper.kicks()

        # when
        collateral_before = self.collateral.gem.balance_of(self.keeper_address)

        # when
        time_travel_by(self.web3, flipper.ttl() + 1)
        lot_won = flipper.bids(kick).lot
        assert lot_won > Wad(0)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        assert self.collateral.adapter.exit(self.keeper_address, lot_won).transact(from_address=self.keeper_address)
        # then
        collateral_after = self.collateral.gem.balance_of(self.keeper_address)
        assert collateral_before < collateral_after

    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self, kick, other_address):
        # given
        flipper = self.collateral.flipper
        # and
        bid = Rad.from_number(66)
        self.tend_with_dai(self.mcd, self.collateral, flipper, kick, other_address, bid)
        assert flipper.bids(kick).bid == bid

        # when
        time_travel_by(self.web3, flipper.ttl() + 1)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then ensure the bid hasn't been deleted
        assert flipper.bids(kick).bid == bid

        # cleanup
        assert flipper.deal(kick).transact()
        assert flipper.bids(kick).bid == Rad(0)

    def test_should_obey_gas_price_provided_by_the_model(self, kick):
        # given
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.simulate_model_bid(self.mcd, self.collateral, model, price=Wad.from_number(15.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.collateral.flipper.bids(kick).bid == Rad(Wad.from_number(15.0) * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self, kick):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        self.simulate_model_bid(self.mcd, self.collateral, model, price=Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick).bid == Rad(Wad.from_number(16.0) * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    def test_should_change_gas_strategy_when_model_output_changes(self, kick):
        # given
        flipper = self.collateral.flipper
        (model, model_factory) = models(self.keeper, kick)

        # when
        first_bid = Wad.from_number(3)
        self.simulate_model_bid(self.mcd, self.collateral, model=model, price=first_bid, gas_price=2000)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 2000

        # when
        second_bid = Wad.from_number(6)
        self.simulate_model_bid(self.mcd, self.collateral, model=model, price=second_bid)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick).bid == Rad(second_bid * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == \
               self.default_gas_price

        # when
        third_bid = Wad.from_number(9)
        new_gas_price = int(self.default_gas_price*1.25)
        self.simulate_model_bid(self.mcd, self.collateral, model=model, price=third_bid, gas_price=new_gas_price)
        # and
        self.keeper.check_all_auctions()
        self.keeper.check_for_bids()
        wait_for_other_threads()
        # then
        assert flipper.bids(kick).bid == Rad(third_bid * tend_lot)
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == new_gas_price

        # cleanup
        time_travel_by(self.web3, flipper.ttl() + 1)
        assert flipper.deal(kick).transact()

    @classmethod
    def teardown_class(cls):
        flog_and_heal(web3(), mcd(web3()), past_blocks=1200, require_heal=False)
