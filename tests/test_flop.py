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

from auction_keeper.main import AuctionKeeper
from auction_keeper.logic import ModelOutput
from auction_keeper.model import ModelParameters, ModelInput
from pymaker import Address
from pymaker.approval import directly
from pymaker.auctions import Flopper
from pymaker.auth import DSGuard
from pymaker.numeric import Wad
from pymaker.token import DSToken
from tests.helper import args, time_travel_by


class TestAuctionKeeperFlopper:
    def setup_method(self):
        self.web3 = Web3(EthereumTesterProvider())
        self.web3.eth.defaultAccount = self.web3.eth.accounts[0]
        self.keeper_address = Address(self.web3.eth.defaultAccount)
        self.gal_address = Address(self.web3.eth.accounts[1])
        self.other_address = Address(self.web3.eth.accounts[2])
        self.dai = DSToken.deploy(self.web3, 'DAI')
        self.dai.mint(Wad.from_number(10000000)).transact()
        self.dai.transfer(self.other_address, Wad.from_number(1000000)).transact()
        self.mkr = DSToken.deploy(self.web3, 'MKR')
        self.flopper = Flopper.deploy(self.web3, self.dai.address, self.mkr.address)

        # so the Flopper can mint MKR
        dad = DSGuard.deploy(self.web3)
        dad.permit(self.flopper.address, self.mkr.address, DSGuard.ANY).transact()
        self.mkr.set_authority(dad.address).transact()

        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                              f"--flopper {self.flopper.address} "
                                              f"--model ./bogus-model.sh"), web3=self.web3)

        self.keeper.approve()

        self.model = MagicMock()
        self.model.output = MagicMock(return_value=None)
        self.model_factory = self.keeper.auctions.model_factory
        self.model_factory.create_model = MagicMock(return_value=self.model)

    def simulate_model_output(self, price: Wad, gas_price: Optional[int] = None):
        self.model.output = MagicMock(return_value=ModelOutput(price=price, gas_price=gas_price))

    def test_should_start_a_new_model_and_provide_it_with_info_on_auction_kick(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        # then
        self.model_factory.create_model.assert_called_once_with(ModelParameters(flipper=None,
                                                                                flapper=None,
                                                                                flopper=self.flopper.address,
                                                                                id=1))
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(10)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(2)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.gal_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic == 0
        assert self.model.input.call_args[0][0].price == Wad.from_number(5.0)

    def test_should_provide_model_with_updated_info_after_our_own_bid(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count == 1

        # when
        self.simulate_model_output(price=Wad.from_number(50.0))
        # and
        self.keeper.check_all_auctions()
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count > 1
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(10)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(0.2)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.keeper_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].price == Wad.from_number(50.0)

    def test_should_provide_model_with_updated_info_after_somebody_else_bids(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count == 1

        # when
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1), Wad.from_number(10)).transact(from_address=self.other_address)
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.model.input.call_count > 1
        # and
        assert self.model.input.call_args[0][0].bid == Wad.from_number(10)
        assert self.model.input.call_args[0][0].lot == Wad.from_number(1)
        assert self.model.input.call_args[0][0].beg == Wad.from_number(1.05)
        assert self.model.input.call_args[0][0].guy == self.other_address
        assert self.model.input.call_args[0][0].era > 0
        assert self.model.input.call_args[0][0].end > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].tic > self.model.input.call_args[0][0].era + 3600
        assert self.model.input.call_args[0][0].price == Wad.from_number(10.0)

    def test_should_not_do_anything_if_no_output_from_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        previous_block_number = self.web3.eth.blockNumber

        # when
        # [no output from model]
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.web3.eth.blockNumber == previous_block_number

    def test_should_make_initial_bid(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        assert self.flopper.bids(1).lot == Wad.from_number(1.5)

        # when
        self.simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

    #TODO pls reconsider if this is really the behaviour we expect from `auction-keeper`
    #TODO because I don't think it is
    def test_should_not_overbid_itself(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.simulate_model_output(price=Wad.from_number(100.0))
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.1)

        # when
        self.simulate_model_output(price=Wad.from_number(200.0))
        self.keeper.check_all_auctions()
        # then
        assert self.flopper.bids(1).lot == Wad.from_number(0.1)

    def test_should_deal_when_we_won_the_auction(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(1)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.mkr.balance_of(self.keeper_address) > Wad(0)

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
        # then
        assert self.mkr.balance_of(self.keeper_address) == Wad(0)

    def test_should_obey_gas_price_provided_by_the_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.simulate_model_output(price=Wad.from_number(825.0), gas_price=175000)
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == 175000

    def test_should_use_default_gas_price_if_not_provided_by_the_model(self):
        # given
        self.flopper.kick(self.gal_address, Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        self.simulate_model_output(price=Wad.from_number(825.0))
        # and
        self.keeper.check_all_auctions()
        # then
        assert self.web3.eth.getBlock('latest', full_transactions=True).transactions[0].gasPrice == GAS_PRICE
