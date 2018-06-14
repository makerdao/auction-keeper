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

from typing import Optional

from ethereum.tester import GAS_PRICE
from mock import MagicMock
from web3 import Web3, EthereumTesterProvider

from auction_keeper.logic import ModelOutput
from auction_keeper.main import AuctionKeeper
from auction_keeper.model import ModelParameters
from pymaker import Address, Contract
from pymaker.approval import directly
from pymaker.auctions import Flapper, Flipper
from pymaker.numeric import Wad
from pymaker.token import DSToken
from tests.helper import args, time_travel_by


class TestAuctionKeeperFlipper:
    def setup_method(self):
        self.web3 = Web3(EthereumTesterProvider())
        self.web3.eth.defaultAccount = self.web3.eth.accounts[0]
        self.keeper_address = Address(self.web3.eth.defaultAccount)
        self.gal_address = Address(self.web3.eth.accounts[1])
        self.other_address = Address(self.web3.eth.accounts[2])

        # we need VatMock to mock Vat, as Flipper won't work without it
        vat_abi = Contract._load_abi(__name__, '../lib/pymaker/tests/abi/VatMock.abi')
        vat_bin = Contract._load_bin(__name__, '../lib/pymaker/tests/abi/VatMock.bin')
        self.vat_address = Contract._deploy(self.web3, vat_abi, vat_bin, [])
        self.vat_contract = self.web3.eth.contract(abi=vat_abi)(address=self.vat_address.address)

        self.flipper = Flipper.deploy(self.web3, self.vat_address, 123)

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--flipper {self.flipper.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)

        self.keeper.approve()

        # So that `keeper_address` and `other_address` can bid in auctions,
        # they both need to have DAI in their accounts.
        self.vat_contract.transact().mint(self.keeper_address.address, Wad.from_number(10000000).value)
        self.vat_contract.transact().mint(self.other_address.address, Wad.from_number(10000000).value)

        self.model = MagicMock()
        self.model.output = MagicMock(return_value=None)
        self.model_factory = self.keeper.auctions.model_factory
        self.model_factory.create_model = MagicMock(return_value=self.model)

    def simulate_model_output(self, price: Wad, gas_price: Optional[int] = None):
        self.model.output = MagicMock(return_value=ModelOutput(price=price, gas_price=gas_price))

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        # then
        self.model_factory.create_model.assert_called_once_with(ModelParameters(flipper=self.flipper.address,
                                                                                flapper=None,
                                                                                flopper=None,
                                                                                id=1))
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(1000)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(100)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.gal_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic == 0
        assert self.model.input.call_args[0][0].price == Wad.from_number(10.0)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count == 1

        # when
        self.simulate_model_output(price=Wad.from_number(15.0))
        # and
        self.keeper.check_all_auctions()
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count > 1
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(1500)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(100)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.keeper_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].price == Wad.from_number(15.0)

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count == 1

        # when
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1700)).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count > 1
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(1700)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(100)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.other_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].price == Wad.from_number(17.0)

    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    def test_should_make_initial_bid(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)

        # when
        self.simulate_model_output(price=Wad.from_number(16.0))
        # and
        self.keeper.check_all_auctions()
        # then
        auction = self.flipper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(16.0), 2)

    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        self.flipper.kick(self.gal_address, self.gal_address, Wad.from_number(5000), Wad.from_number(100), Wad.from_number(1000)) \
            .transact(from_address=self.gal_address)
        # and
        self.flipper.tend(1, Wad.from_number(100), Wad.from_number(1600)).transact(from_address=self.other_address)
        assert self.flipper.bids(1).bid == Wad.from_number(1600)

        # when
        self.simulate_model_output(price=Wad.from_number(19.0))
        # and
        self.keeper.check_all_auctions()
        # then
        auction = self.flipper.bids(1)
        assert self.flipper.bids(1).bid == Wad.from_number(1900)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(19.0), 2)

    # #TODO pls reconsider if this is really the behaviour we expect from `auction-keeper`
    # #TODO because I don't think it is
    # def test_should_not_overbid_itself(self):
    #     # given
    #     self.flipper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
    #
    #     # when
    #     self.simulate_model_output(price=Wad.from_number(10.0))
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.flipper.bids(1).bid == Wad.from_number(20.0)
    #
    #     # when
    #     self.simulate_model_output(price=Wad.from_number(5.0))
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.flipper.bids(1).bid == Wad.from_number(20.0)
    #
    # def test_should_deal_when_we_won_the_auction(self):
    #     # given
    #     self.flipper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
    #
    #     # when
    #     self.simulate_model_output(price=Wad.from_number(10.0))
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     auction = self.flipper.bids(1)
    #     assert round(auction.lot / auction.bid, 2) == round(Wad.from_number(10.0), 2)
    #     assert self.dai.balance_of(self.keeper_address) == Wad(0)
    #
    #     # when
    #     time_travel_by(self.web3, self.flipper.ttl() + 5)
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.dai.balance_of(self.keeper_address) > Wad(0)
    #
    # def test_should_not_deal_when_auction_finished_but_somebody_else_won(self):
    #     # given
    #     self.flipper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
    #     # and
    #     self.flipper.approve(directly(from_address=self.other_address))
    #     self.flipper.tend(1, Wad.from_number(200), Wad.from_number(16)).transact(from_address=self.other_address)
    #     assert self.flipper.bids(1).bid == Wad.from_number(16)
    #
    #     # when
    #     time_travel_by(self.web3, self.flipper.ttl() + 5)
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.dai.balance_of(self.keeper_address) == Wad(0)
    #
    # def test_should_obey_gas_price_provided_by_the_model(self):
    #     # given
    #     self.flipper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
    #
    #     # when
    #     self.simulate_model_output(price=Wad.from_number(10.0), gas_price=175000)
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000
    #
    # def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
    #     # given
    #     self.flipper.kick(self.gal_address, Wad.from_number(200), Wad.from_number(10)).transact(from_address=self.gal_address)
    #
    #     # when
    #     self.simulate_model_output(price=Wad.from_number(10.0))
    #     # and
    #     self.keeper.check_all_auctions()
    #     # then
    #     assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == GAS_PRICE
