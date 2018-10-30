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
import asyncio
import logging
import sys
import threading

from pymaker.dss import Ilk, Cat, Pit, Vat, Urn, DaiVat
from pymaker.token import DSToken
from web3 import Web3, HTTPProvider

from auction_keeper.model import ModelFactory
from auction_keeper.gas import UpdatableGasPrice
from auction_keeper.logic import Auction, Status, Auctions, Stance
from auction_keeper.strategy import FlopperStrategy, FlapperStrategy, FlipperStrategy, CatStrategy
from pymaker import Address, Wad, TransactStatus
from pymaker.approval import directly
from pymaker.auctions import Flopper, Flipper, Flapper
from pymaker.gas import FixedGasPrice, DefaultGasPrice
from pymaker.lifecycle import Lifecycle


class AuctionKeeper:
    logger = logging.getLogger()

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

        parser.add_argument('--cat', type=str, help="Ethereum address of the Cat contract")

        parser.add_argument('--ilk', type=str, help="Ilk used for this keeper")

        contract = parser.add_mutually_exclusive_group(required=True)
        contract.add_argument('--flipper', type=str, help="Ethereum address of the Flipper contract")
        contract.add_argument('--flapper', type=str, help="Ethereum address of the Flapper contract")
        contract.add_argument('--flopper', type=str, help="Ethereum address of the Flopper contract")

        parser.add_argument("--model", type=str, required=True,
                            help="Commandline to use in order to start the bidding model")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else Web3(
            HTTPProvider(endpoint_uri=f"http://{self.arguments.rpc_host}:{self.arguments.rpc_port}",
                         request_kwargs={"timeout": self.arguments.rpc_timeout}))
        self.web3.eth.defaultAccount = self.arguments.eth_from
        self.our_address = Address(self.arguments.eth_from)

        self.cat = Cat(web3=self.web3, address=Address(self.arguments.cat)) if self.arguments.cat else None
        self.ilk = Ilk(self.arguments.ilk) if self.arguments.ilk else None

        self.flipper = Flipper(web3=self.web3,
                               address=Address(self.arguments.flipper)) if self.arguments.flipper else None
        self.flapper = Flapper(web3=self.web3,
                               address=Address(self.arguments.flapper)) if self.arguments.flapper else None
        self.flopper = Flopper(web3=self.web3,
                               address=Address(self.arguments.flopper)) if self.arguments.flopper else None

        if self.flipper:
            self.strategy = FlipperStrategy(self.flipper)
            if self.cat is None:
                self.logger.warning(f"Flipper auction selected but no Cat address specified so we won't bite()")
                if self.ilk is None:
                    self.logger.warning(f"bite() will operate on all CDP type because ilk is not specified")
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
            if self.flipper and self.cat:
                def seq_func():
                    self.check_cdps()
                    self.check_all_auctions()
                lifecycle.on_block(seq_func)
            else:
                lifecycle.on_block(self.check_all_auctions)

    def startup(self):
        self.approve()

    def approve(self):
        self.strategy.approve()

    def check_cdps(self):
        self.logger.warning('test1')
        last_frob_event = {}
        pit = Pit(self.web3, self.cat.pit())
        vat = Vat(self.web3, self.cat.vat())

        # Look for unsafe CDPs and bite them
        frob_filter = {}
        if self.ilk:
            frob_filter = {'ilk': self.ilk.toBytes()}

        past_frob = pit.past_frob(self.web3.eth.blockNumber, event_filter=frob_filter)  # TODO: put past_block in cache
        for frob_event in past_frob:
            last_frob_event[frob_event.urn.address] = frob_event

        for urn_addr in last_frob_event:
            ilk = last_frob_event[urn_addr].ilk
            current_urn = vat.urn(ilk, urn_addr)
            safe = current_urn.ink * pit.spot(ilk) >= current_urn.art * vat.ilk(ilk.name).rate
            if not safe:
                self.logger.info(f'Found an unsafe CDP: {current_urn}')
                # TODO this should happen asynchronously
                self.cat.bite(ilk, current_urn).transact()

        # Look for pending collateral auctions and start them when DAI balance is sufficient
        for i in range(self.cat.nflip()):
            flip = self.cat.flips(i)

            # Check both debt and if this auction-keeper will handle the auction
            if flip.tab > Wad(0) and (self.cat.flipper(flip.urn.ilk) == self.flipper.address):
                self.logger.info(f'Found an outstanding collateral auction: {flip}')

                # Check our balance and if balances available then flip() an auction
                dai_balance = Wad(vat.dai(self.our_address))
                lump = self.cat.lump(flip.urn.ilk)

                if flip.tab < lump and dai_balance > flip.tab:
                    # TODO this should happen asynchronously
                    self.cat.flip(flip, flip.tab).transact()
                elif flip.tab > lump and dai_balance > lump:
                    # TODO this should happen asynchronously
                    self.cat.flip(flip, lump).transact()
                else:
                    self.logger.warning(f'Not enought balance to flip({flip.id}): '
                                        f'dai_balance={dai_balance} tab={flip.tab} lump={lump}')

    def check_all_auctions(self):
        self.logger.warning('test2')
        for id in range(1, self.strategy.kicks() + 1):
            self.check_auction(id)

    # TODO if we will introduce multithreading here, proper locking should be introduced as well
    #     locking should not happen on `auction.lock`, but on auction.id here. as sometimes we will
    #     intend to lock on auction id but not create `Auction` object for it (as the auction is already finished
    #     for example).
    def check_auction(self, id: int):
        assert (isinstance(id, int))

        # Read auction information
        input = self.strategy.get_input(id)
        auction_missing = (input.end == 0)
        auction_finished = (input.tic < input.era and input.tic != 0) or (input.end < input.era)

        if auction_missing:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)

        # Check if the auction is finished.
        # If it is finished and we are the winner, `deal` the auction.
        # If it is finished and we aren't the winner, there is no point in carrying on with this auction.
        elif auction_finished:
            if input.guy == self.our_address:
                # TODO this should happen asynchronously

                # Always using default gas price for `deal`
                self.strategy.deal(id).transact(gas_price=DefaultGasPrice())

            else:
                # Try to remove the auction so the model terminates and we stop tracking it.
                # If auction has already been removed, nothing happens.
                self.auctions.remove_auction(id)

        else:
            auction = self.auctions.get_auction(id)

            # Feed the model with current state
            auction.feed_model(input)

            output = auction.model_output()
            if output is not None:
                bid_price, bid_transact = self.strategy.bid(id, output.price)

                if bid_price is not None and bid_transact is not None:
                    # if no transaction in progress, send a new one
                    transaction_in_progress = auction.transaction_in_progress()
                    if transaction_in_progress is None:
                        self.logger.info(f"Sending new bid @{output.price} (gas_price={output.gas_price})")

                        auction.price = bid_price
                        auction.gas_price = UpdatableGasPrice(output.gas_price)
                        auction.register_transaction(bid_transact)

                        self._run_future(bid_transact.transact_async(gas_price=auction.gas_price))

                    # if transaction in progress and gas price went up...
                    elif output.gas_price > auction.gas_price.gas_price:

                        # ...replace the entire bid if the price has changed...
                        if bid_price != auction.price:
                            self.logger.info(
                                f"Overriding pending bid with new bid @{output.price} (gas_price={output.gas_price})")

                            auction.price = bid_price
                            auction.gas_price = UpdatableGasPrice(output.gas_price)
                            auction.register_transaction(bid_transact)

                            self._run_future(bid_transact.transact_async(replace=transaction_in_progress,
                                                                         gas_price=auction.gas_price))

                        # ...or just replace gas_price if price stays the same
                        else:
                            self.logger.info(f"Overriding pending bid with new gas_price ({output.gas_price})")

                            auction.gas_price.update_gas_price(output.gas_price)

    @staticmethod
    def _run_future(future):
        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                asyncio.get_event_loop().run_until_complete(future)
            finally:
                loop.close()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()


if __name__ == '__main__':
    AuctionKeeper(sys.argv[1:]).main()
