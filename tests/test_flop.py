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

from web3 import Web3, EthereumTesterProvider

from auction_keeper.main import AuctionKeeper
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
        self.our_address = Address(self.web3.eth.defaultAccount)
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

    def test_should_make_initial_bid(self):
        # given
        keeper = AuctionKeeper(args=args(f"--eth-from {self.web3.eth.defaultAccount} "
                                         f"--flopper {self.flopper.address}"), web3=self.web3)
        # and
        keeper.approve()
        # and
        self.flopper.kick(Address(self.web3.eth.accounts[1]), Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        keeper.drive(1, Wad.from_number(825.0))
        # and
        keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(self.flopper.kicks())
        assert auction.lot < Wad.from_number(2)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.our_address) == Wad(0)

    def test_should_bid_even_if_there_is_already_a_bidder(self):
        # given
        keeper = AuctionKeeper(args=args(f"--eth-from {self.web3.eth.defaultAccount} "
                                         f"--flopper {self.flopper.address}"), web3=self.web3)
        # and
        keeper.approve()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.kick(Address(self.web3.eth.accounts[1]), Wad.from_number(2), Wad.from_number(10)).transact()
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        assert self.flopper.bids(self.flopper.kicks()).lot == Wad.from_number(1.5)

        # when
        keeper.drive(1, Wad.from_number(825.0))
        # and
        keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(self.flopper.kicks())
        assert auction.lot < Wad.from_number(1.5)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)
        assert self.mkr.balance_of(self.our_address) == Wad(0)

    def test_should_deal_when_we_won_the_auction(self):
        # given
        keeper = AuctionKeeper(args=args(f"--eth-from {self.web3.eth.defaultAccount} "
                                         f"--flopper {self.flopper.address}"), web3=self.web3)
        # and
        keeper.approve()
        # and
        self.flopper.kick(Address(self.web3.eth.accounts[1]), Wad.from_number(2), Wad.from_number(10)).transact()

        # when
        keeper.drive(1, Wad.from_number(825.0))
        # and
        keeper.check_all_auctions()
        # then
        auction = self.flopper.bids(self.flopper.kicks())
        assert auction.lot < Wad.from_number(2)
        assert round(auction.bid / auction.lot, 2) == round(Wad.from_number(825.0), 2)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        keeper.check_all_auctions()
        # then
        assert self.mkr.balance_of(self.our_address) > Wad(0)

    def test_should_not_deal_when_auction_finished_but_somebody_else_won(self):
        # given
        keeper = AuctionKeeper(args=args(f"--eth-from {self.web3.eth.defaultAccount} "
                                         f"--flopper {self.flopper.address}"), web3=self.web3)
        # and
        keeper.approve()
        # and
        self.flopper.approve(directly(from_address=self.other_address))
        self.flopper.kick(Address(self.web3.eth.accounts[1]), Wad.from_number(2), Wad.from_number(10)).transact()
        self.flopper.dent(1, Wad.from_number(1.5), Wad.from_number(10)).transact(from_address=self.other_address)
        assert self.flopper.bids(self.flopper.kicks()).lot == Wad.from_number(1.5)

        # when
        time_travel_by(self.web3, self.flopper.ttl() + 5)
        # and
        keeper.check_all_auctions()
        # then
        assert self.mkr.balance_of(self.our_address) == Wad(0)
