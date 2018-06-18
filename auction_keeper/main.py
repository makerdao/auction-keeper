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

import argparse
import logging
import sys

from web3 import Web3, HTTPProvider

from auction_keeper.process_model import ModelFactory
from auction_keeper.gas import UpdatableGasPrice
from auction_keeper.logic import Auction, ModelInput, Auctions, ModelOutput
from auction_keeper.strategy import FlopperStrategy, FlapperStrategy, FlipperStrategy
from pymaker import Address, Wad
from pymaker.approval import directly
from pymaker.auctions import Flopper, Flipper, Flapper
from pymaker.gas import FixedGasPrice, DefaultGasPrice
from pymaker.lifecycle import Lifecycle


class AuctionKeeper:
    def __init__(self, args: list, **kwargs):
        parser = argparse.ArgumentParser(prog='auction-keeper')

        parser.add_argument("--rpc-host", type=str, default="localhost",
                            help="JSON-RPC host (default: `localhost')")

        parser.add_argument("--rpc-port", type=int, default=8545,
                            help="JSON-RPC port (default: `8545')")

        parser.add_argument("--rpc-timeout", type=int, default=10,
                            help="JSON-RPC timeout (in seconds, default: 10)")

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum account from which to send transactions")

        contract = parser.add_mutually_exclusive_group(required=True)
        contract.add_argument('--flipper', type=str, help="Ethereum address of the Flipper contract")
        contract.add_argument('--flapper', type=str, help="Ethereum address of the Flapper contract")
        contract.add_argument('--flopper', type=str, help="Ethereum address of the Flopper contract")

        parser.add_argument("--model", type=str, required=True,
                            help="Commandline to run the risk model used for bidding")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        self.web3 = kwargs['web3'] if 'web3' in kwargs else Web3(HTTPProvider(endpoint_uri=f"http://{self.arguments.rpc_host}:{self.arguments.rpc_port}",
                                                                              request_kwargs={"timeout": self.arguments.rpc_timeout}))
        self.web3.eth.defaultAccount = self.arguments.eth_from
        self.our_address = Address(self.arguments.eth_from)

        self.flipper = Flipper(web3=self.web3, address=Address(self.arguments.flipper)) if self.arguments.flipper else None
        self.flapper = Flapper(web3=self.web3, address=Address(self.arguments.flapper)) if self.arguments.flapper else None
        self.flopper = Flopper(web3=self.web3, address=Address(self.arguments.flopper)) if self.arguments.flopper else None

        if self.flipper:
            self.strategy = FlipperStrategy(self.flipper)
        elif self.flapper:
            self.strategy = FlapperStrategy(self.flapper)
        elif self.flopper:
            self.strategy = FlopperStrategy(self.flopper)

        self.auctions = Auctions(flipper=self.flipper.address if self.flipper else None,
                                 flapper=self.flapper.address if self.flapper else None,
                                 flopper=self.flopper.address if self.flopper else None,
                                 model_factory=ModelFactory(self.arguments.model))

        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))
        logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
        logging.getLogger('requests.packages.urllib3.connectionpool').setLevel(logging.INFO)

    def main(self):
        with Lifecycle(self.web3) as lifecycle:
            lifecycle.on_startup(self.startup)
            lifecycle.on_block(self.check_all_auctions)

    def startup(self):
        self.approve()

    def approve(self):
        self.strategy.approve()

    def check_all_auctions(self):
        for auction_id in range(1, self.strategy.kicks() + 1):
            self.check_auction(auction_id)

    #TODO if we will introduce multithreading here, proper locking should be introduced as well
    #     locking should not happen on `auction.lock`, but on auction.id here. as sometimes we will
    #     intend to lock on auction id but not create `Auction` object for it (as the auction is already finished
    #     for example).
    def check_auction(self, auction_id: int):
        assert(isinstance(auction_id, int))

        # Read auction information
        input = self.strategy.get_input(auction_id)
        auction_missing = (input.end == 0)
        auction_finished = (input.tic < input.era and input.tic != 0) or (input.end < input.era)

        print(f"MISSING {auction_missing}")
        print(f"FINISHED {auction_finished}")

        if auction_missing:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(auction_id)

        # Check if the auction is finished.
        # If it is finished and we are the winner, `deal` the auction.
        # If it is finished and we aren't the winner, there is no point in carrying on with this auction.
        elif auction_finished:
            if input.guy == self.our_address:
                # TODO this should happen asynchronously

                # Always using default gas price for `deal`
                self.strategy.deal(auction_id).transact(gas_price=DefaultGasPrice())

            else:
                # Try to remove the auction so the model terminates and we stop tracking it.
                # If auction has already been removed, nothing happens.
                self.auctions.remove_auction(auction_id)

        else:
            auction = self.auctions.get_auction(auction_id)

            # Feed the model with current state
            auction.feed_model(input)

            output = auction.model_output()
            if output is not None:
                bid_transact = self.strategy.bid(auction_id, output.price)

                if bid_transact is not None:
                    gas_price = UpdatableGasPrice(output.gas_price)
                    bid_transact.transact(gas_price=gas_price)


if __name__ == '__main__':
    AuctionKeeper(sys.argv[1:]).main()
