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

import argparse
import asyncio
import logging
import sys
import threading

from web3 import Web3, HTTPProvider

from pymaker import Address, Wad
from pymaker.auctions import Flopper, Flipper, Flapper
from pymaker.dss import Ilk, Cat, Vat, Vow
from pymaker.gas import DefaultGasPrice
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.token import DSToken

from auction_keeper.gas import UpdatableGasPrice
from auction_keeper.logic import Auction, Auctions
from auction_keeper.model import ModelFactory
from auction_keeper.strategy import FlopperStrategy, FlapperStrategy, FlipperStrategy


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

        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=aaa.json,pass_file=aaa.pass')")

        parser.add_argument('--cat', type=str, help="Ethereum address of the Cat contract")
        parser.add_argument('--vow', type=str, help="Ethereum address of the Vow contract")
        parser.add_argument('--mkr', type=str, help="Address of the MKR governance token, required for flap auctions")

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

        if self.arguments.rpc_host.startswith("http"):
            endpoint_uri = f"{self.arguments.rpc_host}:{self.arguments.rpc_port}"
        else:
            # Should probably default this to use TLS, but I don't want to break existing configs
            endpoint_uri = f"http://{self.arguments.rpc_host}:{self.arguments.rpc_port}"

        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else Web3(
            HTTPProvider(endpoint_uri=endpoint_uri,
                         request_kwargs={"timeout": self.arguments.rpc_timeout}))

        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        self.cat = Cat(web3=self.web3, address=Address(self.arguments.cat)) if self.arguments.cat else None
        self.vow = Vow(web3=self.web3, address=Address(self.arguments.vow)) if self.arguments.vow else None
        self.mkr = DSToken(web3=self.web3, address=Address(self.arguments.mkr)) if self.arguments.mkr else None
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
            if self.vow is None:
                self.logger.warning(f"Flapper auction selected but no Vow address specified so we won't flip()")
            self.strategy = FlapperStrategy(self.flapper, self.mkr.address)
        elif self.flopper:
            if self.vow is None:
                self.logger.warning(f"Flopper auction selected but no Vow address specified so we won't flap()")
            if self.cat is None:
                self.logger.warning(f"Flopper auction selected but no Cat address specified so we won't flog()")
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
            elif self.flapper and self.vow:
                def seq_func():
                    self.check_flap()
                    self.check_all_auctions()

                lifecycle.on_block(seq_func)
            elif self.flopper and self.vow:
                def seq_func():
                    self.check_flop()
                    self.check_all_auctions()

                lifecycle.on_block(seq_func)
            else:
                lifecycle.on_block(self.check_all_auctions)
            lifecycle.every(2, self.check_for_bids)

    def startup(self):
        self.approve()

    def approve(self):
        self.strategy.approve()

    def check_cdps(self):
        last_note_event = {}
        vat = Vat(self.web3, self.cat.vat())

        # Look for unsafe CDPs and bite them

        past_frob = vat.past_frob(self.web3.eth.blockNumber, self.ilk)  # TODO: put past_block in cache
        for frob in past_frob:
            last_note_event[frob.urn] = frob

        for urn_addr in last_note_event:
            ilk = vat.ilk(frob.ilk)
            current_urn = vat.urn(ilk, urn_addr)
            safe = current_urn.ink * ilk.spot >= current_urn.art * vat.ilk(ilk.name).rate
            if not safe:
                self.logger.info(f'Found an unsafe CDP: {current_urn}')
                # TODO: Execute this asynchronously, such that it doesn't block detection of new auctions
                #       when the next block is mined.
                self.cat.bite(ilk, current_urn).transact()

        # Cat.bite implicitly kicks off the flip auction; no further action needed.

    def check_flap(self):
        # Check if Vow has a surplus of Dai compared to bad debt
        joy = self.vow.joy()
        awe = self.vow.awe()
        mkr = DSToken(self.web3, self.flapper.gem())

        # Check if Vow has Dai in excess
        if joy > awe:
            bump = self.vow.bump()
            hump = self.vow.hump()

            # Check our balance
            mkr_balance = mkr.balance_of(self.our_address)
            min_balance = Wad(0)  # TODO: determine minimum balance ...

            # Check if Vow has enough Dai surplus to start an auction and that we have enough mkr balance
            if (joy - awe) >= (bump + hump) and mkr_balance > min_balance:
                woe = self.vow.woe()

                # Heal the system to bring Woe to 0
                if woe > Wad(0):
                    self.vow.heal(woe).transact()
                self.vow.flap().transact()

            if (joy - awe) >= (bump + hump) and mkr_balance <= min_balance:
                self.logger.warning('Flap auction is possible but not enough MKR balance available to participate')

    def check_flop(self):
        # Check if Vow has a surplus of bad debt compared to Dai
        joy = self.vow.joy()
        awe = self.vow.awe()
        vat = Vat(self.web3, self.vow.vat())

        # Check if Vow has bad debt in excess
        if joy < awe:
            woe = self.vow.woe()
            sin = self.vow.sin()
            sump = self.vow.sump()

            # Check our balance
            dai_balance = Wad(vat.dai(self.our_address))
            min_balance = Wad(0)  # TODO: determine minimum balance ...

            # Check if Vow has enough bad debt to start an auction and that we have enough dai balance
            if woe + sin >= sump and dai_balance > min_balance:
                # We need to bring Joy to 0 and Woe to at least sump

                # first use kiss() as it settled bad debt already in auctions and doesn't decrease woe
                ash = self.vow.ash()
                if ash > Wad(0):
                    self.vow.kiss(ash).transact()

                # Convert enough sin in woe to have woe >= sump + joy
                if woe < sump and self.cat is not None:
                    flog_amount = Wad(0)
                    for bite_event in self.cat.past_bite(self.web3.eth.blockNumber):  # TODO: cache ?
                        era = bite_event.era(self.web3)
                        sin = self.vow.sin_of(era)
                        if sin > Wad(0):
                            self.vow.flog(era).transact()

                            # flog() sin until woe is above sump + joy
                            if self.vow.woe() - self.vow.joy() >= sump:
                                break

                # use heal() for removing the remaining joy
                joy = self.vow.joy()
                if joy > Wad(0):
                    self.logger.debug(f"healing joy={self.vow.joy()} woe={self.vow.woe()}")
                    self.vow.heal(joy).transact()

                if woe < sump and self.cat is None:
                    self.logger.warning('Not enough woe to flop() and Cat address is not known !')
                else:
                    # Start a flop auction
                    self.vow.flop().transact()

            if woe + sin >= sump and dai_balance <= min_balance:
                self.logger.warning('Flop auction is possible but not enought DAI balance available to participate')

    def check_all_auctions(self):
        for id in range(1, self.strategy.kicks() + 1):
            if self.check_auction(id):
                self.feed_model(id)

    def check_for_bids(self):
        self.logger.debug(f"Checking for bids in {len(self.auctions.auctions)} auctions")
        for id, auction in self.auctions.auctions.items():
            self.handle_bid(id=id, auction=auction)

    # TODO if we will introduce multithreading here, proper locking should be introduced as well
    #     locking should not happen on `auction.lock`, but on auction.id here. as sometimes we will
    #     intend to lock on auction id but not create `Auction` object for it (as the auction is already finished
    #     for example).
    def check_auction(self, id: int) -> bool:
        assert isinstance(id, int)

        # Read auction information
        input = self.strategy.get_input(id)
        auction_missing = (input.end == 0)
        auction_finished = (input.tic < input.era and input.tic != 0) or (input.end < input.era)

        if auction_missing:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            return False

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
            return False

        else:
            return True

    def feed_model(self, id: int):
        assert isinstance(id, int)

        auction = self.auctions.get_auction(id)
        input = self.strategy.get_input(id)

        # Feed the model with current state
        auction.feed_model(input)

    def handle_bid(self, id: int, auction: Auction):
        assert isinstance(id, int)
        assert isinstance(auction, Auction)

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
                elif output.gas_price and output.gas_price > auction.gas_price.gas_price:

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
