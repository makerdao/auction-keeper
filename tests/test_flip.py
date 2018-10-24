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

from typing import Optional

from mock import MagicMock
from pymaker.deployment import DssDeployment
from pymaker.dss import Urn, Collateral
from web3 import Web3, HTTPProvider

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import Parameters
from pymaker import Address, Contract
from pymaker.auctions import Flipper
from pymaker.numeric import Wad, Ray
from pymaker.token import DSToken
from tests.helper import args, time_travel_by, wait_for_other_threads, TransactionIgnoringTest


@pytest.fixture(scope="session")
def web3():
    web3 = Web3(HTTPProvider("http://localhost:8555"))
    web3.eth.defaultAccount = web3.eth.accounts[0]
    return web3


@pytest.fixture(scope="session")
def our_address(web3):
    return Address(web3.eth.accounts[0])


@pytest.fixture(scope="session")
def keeper_address(web3):
    return Address(web3.eth.accounts[1])


@pytest.fixture(scope="session")
def other_address(web3):
    return Address(web3.eth.accounts[2])


@pytest.fixture(scope="session")
def gal_address(web3):
    return Address(web3.eth.accounts[3])


@pytest.fixture(scope="session")
def d(web3, our_address, other_address, gal_address):
    d = DssDeployment.deploy(web3=web3, debt_ceiling=Wad.from_number(1000000))

    # mint gem for cdp frob() by gal_address
    for c in d.collaterals:
        assert c.gem.mint(Wad.from_number(1000000)).transact()
        assert c.gem.transfer(gal_address, Wad.from_number(1000000)).transact()

        # Require to join the adapter
        assert c.gem.approve(c.adapter.address).transact(from_address=gal_address)

        # Liquidation Quantity at 100
        assert d.cat.file_lump(c.ilk, Wad.from_number(100)).transact()

    # mint dai for auction participant
    assert d.dai.mint(Wad.from_number(20000000)).transact()
    assert d.dai.transfer(other_address, Wad.from_number(10000000)).transact()

    return d


@pytest.fixture(scope="session")
def c(d: DssDeployment):
    return d.collaterals[0]


@pytest.fixture()
def keeper(web3, c: Collateral, keeper_address: Address, d: DssDeployment):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def unsafe_cdp(our_address, gal_address, d: DssDeployment, c: Collateral):
    # Add collateral to gal CDP
    assert c.adapter.join(Urn(gal_address), Wad.from_number(1)).transact(from_address=gal_address)
    assert d.pit.frob(c.ilk, Wad.from_number(1), Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    our_urn = d.vat.urn(c.ilk, gal_address)
    max_dart = our_urn.ink * d.pit.spot(c.ilk) - our_urn.art
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    assert d.pit.frob(c.ilk, Wad(0), max_dart).transact(from_address=gal_address)

    # Manipulate price to make gal CDP underwater
    assert c.pip.poke_with_int(to_price.value).transact(from_address=our_address)  # TODO: why our_address here ?
    assert c.spotter.poke().transact()

    return d.vat.urn(c.ilk, gal_address)


@pytest.fixture()
def bid_id(unsafe_cdp: Urn, d: DssDeployment, c: Collateral):
    # Bite gal CDP
    flip_id = d.cat.nflip()
    assert d.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()

    # Kick one flip auction
    flip = d.cat.flips(flip_id)
    lump = d.cat.lump(flip.urn.ilk)
    assert d.cat.flip(flip, lump).transact()

    return c.flipper.kicks()


class TestAuctionKeeperFlipper(TransactionIgnoringTest):
    def setup_method(self):
        self.web3 = Web3(HTTPProvider("http://localhost:8555"))
        self.web3.eth.defaultAccount = self.web3.eth.accounts[0]
        self.keeper_address = Address(self.web3.eth.defaultAccount)
        self.gal_address = Address(self.web3.eth.accounts[1])
        self.other_address = Address(self.web3.eth.accounts[2])

        # GemMock version of DSToken with push(bytes32, uint function) an hope(address)
        gem_abi = Contract._load_abi(__name__, '../lib/pymaker/tests/abi/GemMock.abi')
        gem_bin = Contract._load_bin(__name__, '../lib/pymaker/tests/abi/GemMock.bin')

        self.gem_addr = Contract._deploy(self.web3, gem_abi, gem_bin, [b'ABC'])
        self.gem = DSToken(web3=self.web3, address=self.gem_addr)

        self.dai_addr = Contract._deploy(self.web3, gem_abi, gem_bin, [b'DAI'])
        self.dai = DSToken(web3=self.web3, address=self.dai_addr)

        self.flipper = Flipper.deploy(self.web3, self.dai.address, self.gem.address)

        # Set allowance to allow flipper to move dai and gem
        self.dai.approve(self.flipper.address).transact()
        self.dai.approve(self.flipper.address).transact(from_address=self.gal_address)
        self.dai.approve(self.flipper.address).transact(from_address=self.other_address)
        self.gem.approve(self.flipper.address).transact(from_address=self.gal_address)
        self.gem.approve(self.flipper.address).transact(from_address=self.other_address)

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--flipper {self.flipper.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)

        self.keeper.approve()

        # So that `keeper_address` and `other_address` can bid in auctions,
        # they both need to have DAI in their accounts.
        self.dai.mint(Wad.from_number(20000000)).transact()
        self.dai.transfer(self.other_address, Wad.from_number(10000000)).transact()

        # So that `gal_address` can kick auction he need to have GEM in his accounts
        self.gem.mint(Wad.from_number(1000000)).transact()
        self.gem.transfer(self.gal_address, Wad.from_number(1000000)).transact()

        self.model = MagicMock()
        self.model.get_stance = MagicMock(return_value=None)
        self.model_factory = self.keeper.auctions.model_factory
        self.model_factory.create_model = MagicMock(return_value=self.model)

    def gem_balance(self, address: Address) -> Wad:
        assert (isinstance(address, Address))
        return Wad(self.gem.balance_of(address))

    def simulate_model_output(self, price: Wad, gas_price: Optional[int] = None):
        self.model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))

    def models(self, keeper):
        model = MagicMock()
        model.get_stance = MagicMock(return_value=None)
        model_factory = keeper.auctions.model_factory
        model_factory.create_model = MagicMock(return_value=model)

        return (model, model_factory)

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self, bid_id, d, keeper, c):
        # given
        (model, model_factory) = self.models(keeper)

        # when
        keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        model_factory.create_model.assert_called_once_with(Parameters(flipper=c.flipper.address,
                                                                      flapper=None,
                                                                      flopper=None,
                                                                      id=bid_id))
        # and
        assert model.send_status.call_args[0][0].id == bid_id
        assert model.send_status.call_args[0][0].flipper == c.flipper.address
        assert model.send_status.call_args[0][0].flapper is None
        assert model.send_status.call_args[0][0].flopper is None
        assert model.send_status.call_args[0][0].bid == Wad.from_number(0)
        assert model.send_status.call_args[0][0].lot == Wad(684931506849315068)
        assert model.send_status.call_args[0][0].tab == Wad.from_number(100)
        assert model.send_status.call_args[0][0].beg == Ray.from_number(1.05)
        assert model.send_status.call_args[0][0].guy == d.cat.address
        assert model.send_status.call_args[0][0].era > 0
        assert model.send_status.call_args[0][0].end < model.send_status.call_args[0][0].era + c.flipper.tau() + 1
        assert model.send_status.call_args[0][0].tic == 0
        assert model.send_status.call_args[0][0].price == Wad(0)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count == 1

        # when
        self.simulate_model_output(price=Wad.from_number(15.0))
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
        assert self.model.send_status.call_args[0][0].flipper == self.flipper.address
        assert self.model.send_status.call_args[0][0].flapper is None
        assert self.model.send_status.call_args[0][0].flopper is None
        assert self.model.send_status.call_args[0][0].bid == Wad.from_number(1500)
        assert self.model.send_status.call_args[0][0].lot == Wad.from_number(100)
        assert self.model.send_status.call_args[0][0].tab == Wad.from_number(5000)
        assert self.model.send_status.call_args[0][0].beg == Ray.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.keeper_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(15.0)

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count == 1

        # when
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1700)).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        assert self.model.send_status.call_count > 1
        # and
        assert self.model.send_status.call_args[0][0].id == 1
        assert self.model.send_status.call_args[0][0].flipper == self.flipper.address
        assert self.model.send_status.call_args[0][0].flapper is None
        assert self.model.send_status.call_args[0][0].flopper is None
        assert self.model.send_status.call_args[0][0].bid == Wad.from_number(1700)
        assert self.model.send_status.call_args[0][0].lot == Wad.from_number(100)
        assert self.model.send_status.call_args[0][0].tab == Wad.from_number(5000)
        assert self.model.send_status.call_args[0][0].beg == Ray.from_number(1.05)
        assert self.model.send_status.call_args[0][0].guy == self.other_address
        assert self.model.send_status.call_args[0][0].era > 0
        assert self.model.send_status.call_args[0][0].end > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].tic > self.model.send_status.call_args[0][0].era + 3600
        assert self.model.send_status.call_args[0][0].price == Wad.from_number(17.0)

    def test_should_terminate_model_if_auction_expired_due_to_tau(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        time_travel_by(self.web3, self.flipper.tau() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_expired_due_to_ttl_and_somebody_else_won_it(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flipper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

    def test_should_terminate_model_if_auction_is_dealt(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100),
                          Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_not_called()

        # when
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=self.other_address)
        # and
        time_travel_by(self.web3, self.flipper.ttl() + 5)
        # and
        self.flipper.deal(1).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        wait_for_other_threads()
        # then
        self.model_factory.create_model.assert_called_once()
        self.model.terminate.assert_called_once()

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
