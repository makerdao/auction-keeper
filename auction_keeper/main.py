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

import argparse
import asyncio
import logging
import sys
import threading

from web3 import Web3, HTTPProvider

from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.deployment import DssDeployment
from pymaker.gas import DefaultGasPrice
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad, Ray, Rad

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

        parser.add_argument('--network', type=str, required=True,
                            help="Ethereum network to connect (e.g. 'kovan' or 'testnet')")
        parser.add_argument('--type', type=str, choices=['flip', 'flap', 'flop'],
                            help="Auction type in which to participate")
        parser.add_argument('--ilk', type=str,
                            help="Name of the collateral type for a flip keeper (e.g. 'ETH-B', 'ZRX-A')")
        parser.add_argument('--bid-only', dest='create_auctions', action='store_false',
                            help="Do not take opportunities to create new auctions")

        parser.add_argument('--vat-dai-target', type=float,
                            help="Amount of Dai to keep in the Vat contract (e.g. 2000)")
        parser.add_argument('--keep-dai-in-vat-on-exit', dest='exit_dai_on_shutdown', action='store_false',
                            help="Retain Dai in the Vat on exit, saving gas when restarting the keeper")
        parser.add_argument('--keep-gem-in-vat-on-exit', dest='exit_gem_on_shutdown', action='store_false',
                            help="Retain collateral in the Vat on exit")

        parser.add_argument("--model", type=str, required=True,
                            help="Commandline to use in order to start the bidding model")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        # Configure connection to the chain
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

        # Configure core and token contracts
        if self.arguments.type == 'flip' and not self.arguments.ilk:
            raise RuntimeError("--ilk must be supplied when configuring a flip keeper")
        mcd = DssDeployment.from_network(web3=self.web3, network=self.arguments.network)
        self.vat = mcd.vat
        self.cat = mcd.cat
        self.vow = mcd.vow
        self.mkr = mcd.mkr
        self.dai_join = mcd.dai_adapter
        if self.arguments.type == 'flip':
            self.collateral = mcd.collaterals[self.arguments.ilk]
            self.ilk = self.collateral.ilk
            self.gem_join = self.collateral.adapter
        else:
            self.collateral = None
            self.ilk = None
            self.gem_join = None

        # Configure auction contracts
        self.flipper = self.collateral.flipper if self.arguments.type == 'flip' else None
        self.flapper = mcd.flapper if self.arguments.type == 'flap' else None
        self.flopper = mcd.flopper if self.arguments.type == 'flop' else None
        if self.flipper:
            self.strategy = FlipperStrategy(self.flipper)
        elif self.flapper:
            self.strategy = FlapperStrategy(self.flapper, self.mkr.address)
        elif self.flopper:
            self.strategy = FlopperStrategy(self.flopper)

        # Create the collection used to manage auctions relevant to this keeper
        self.auctions = Auctions(flipper=self.flipper.address if self.flipper else None,
                                 flapper=self.flapper.address if self.flapper else None,
                                 flopper=self.flopper.address if self.flopper else None,
                                 model_factory=ModelFactory(self.arguments.model))
        self.auctions_lock = threading.Lock()

        self.vat_dai_target = Wad.from_number(self.arguments.vat_dai_target) if \
            self.arguments.vat_dai_target is not None else None

        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))
        logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
        logging.getLogger('requests.packages.urllib3.connectionpool').setLevel(logging.INFO)

    def main(self):
        with Lifecycle(self.web3) as lifecycle:
            lifecycle.on_startup(self.startup)
            lifecycle.on_shutdown(self.shutdown)
            if self.flipper and self.cat:
                def seq_func():
                    if self.arguments.create_auctions:
                        self.check_cdps()
                    self.check_all_auctions()

                lifecycle.on_block(seq_func)
            elif self.flapper and self.vow:
                def seq_func():
                    if self.arguments.create_auctions:
                        self.check_flap()
                    self.check_all_auctions()

                lifecycle.on_block(seq_func)
            elif self.flopper and self.vow:
                def seq_func():
                    if self.arguments.create_auctions:
                        self.check_flop()
                    self.check_all_auctions()

                lifecycle.on_block(seq_func)
            else:
                lifecycle.on_block(self.check_all_auctions)
            lifecycle.every(2, self.check_for_bids)

    def startup(self):
        self.approve()
        self.rebalance_dai()
        if self.flapper:
            self.logger.info(f"MKR balance is {self.mkr.balance_of(self.our_address)}")

    def approve(self):
        self.strategy.approve()
        if self.dai_join:
            self.dai_join.approve(hope_directly(), self.vat.address)
            self.dai_join.dai().approve(self.dai_join.address).transact()

    def shutdown(self):
        self.exit_dai_on_shutdown()
        self.exit_collateral_on_shutdown()

    def exit_dai_on_shutdown(self):
        if not self.arguments.exit_dai_on_shutdown or not self.dai_join:
            return

        vat_balance = Wad(self.vat.dai(self.our_address))
        if vat_balance > Wad(0):
            self.logger.info(f"Exiting {str(vat_balance)} Dai from the Vat before shutdown")
            assert self.dai_join.exit(self.our_address, vat_balance).transact()

    def exit_collateral_on_shutdown(self):
        if not self.arguments.exit_gem_on_shutdown or not self.gem_join:
            return

        vat_balance = self.vat.gem(self.ilk, self.our_address)
        if vat_balance > Wad(0):
            self.logger.info(f"Exiting {str(vat_balance)} {self.ilk.name} from the Vat before shutdown")
            assert self.gem_join.exit(self.our_address, vat_balance).transact()

    def check_cdps(self):
        last_note_event = {}

        # Look for unsafe CDPs and bite them
        past_frob = self.vat.past_frob(self.web3.eth.blockNumber, self.ilk)
        for frob in past_frob:
            last_note_event[frob.urn] = frob

        for urn_addr in last_note_event:
            ilk = self.vat.ilk(frob.ilk)
            current_urn = self.vat.urn(ilk, urn_addr)
            rate = self.vat.ilk(ilk.name).rate
            safe = current_urn.ink * ilk.spot >= current_urn.art * rate
            if not safe:
                self._run_future(self.cat.bite(ilk, current_urn).transact_async())

        # Cat.bite implicitly kicks off the flip auction; no further action needed.

    def check_flap(self):
        # Check if Vow has a surplus of Dai compared to bad debt
        joy = self.vat.dai(self.vow.address)
        awe = self.vat.sin(self.vow.address)

        # Check if Vow has Dai in excess
        if joy > awe:
            bump = self.vow.bump()
            hump = self.vow.hump()

            # Check if Vow has enough Dai surplus to start an auction and that we have enough mkr balance
            if (joy - awe) >= (bump + hump):
                woe = self.vow.woe()
                # Heal the system to bring Woe to 0
                if woe > Rad(0):
                    self.vow.heal(woe).transact()
                self.vow.flap().transact()

    def check_flop(self):
        # Check if Vow has a surplus of bad debt compared to Dai
        joy = self.vat.dai(self.vow.address)
        awe = self.vat.sin(self.vow.address)

        # Check if Vow has bad debt in excess
        if joy < awe:
            woe = self.vow.woe()
            sin = self.vow.sin()
            sump = self.vow.sump()
            wait = self.vow.wait()

            # Check if Vow has enough bad debt to start an auction and that we have enough dai balance
            if woe + sin >= sump:
                # We need to bring Joy to 0 and Woe to at least sump

                # first use kiss() as it settled bad debt already in auctions and doesn't decrease woe
                ash = self.vow.ash()
                goodnight = min(ash, joy)
                if goodnight > Rad(0):
                    self.vow.kiss(goodnight).transact()

                # Convert enough sin in woe to have woe >= sump + joy
                if woe < (sump + joy) and self.cat is not None:
                    for bite_event in self.cat.past_bite(self.web3.eth.blockNumber):  # TODO: cache ?
                        era = bite_event.era(self.web3)
                        now = self.web3.eth.getBlock('latest')['timestamp']
                        sin = self.vow.sin_of(era)
                        # If the bite hasn't already been flogged and has aged past the `wait`
                        if sin > Rad(0) and era + wait <= now:
                            self.vow.flog(era).transact()

                            # flog() sin until woe is above sump + joy
                            joy = self.vat.dai(self.vow.address)
                            if self.vow.woe() - joy >= sump:
                                break

                # use heal() for reconciling the remaining joy
                joy = self.vat.dai(self.vow.address)
                if Rad(0) < joy <= self.vow.woe():
                    self.vow.heal(joy).transact()
                    # heal() changes joy and woe (the balance of surplus and debt)
                    joy = self.vat.dai(self.vow.address)

                woe = self.vow.woe()
                if sump <= woe and joy == Rad(0):
                    self.vow.flop().transact()

    def check_all_auctions(self):
        for id in range(1, self.strategy.kicks() + 1):
            with self.auctions_lock:
                if self.check_auction(id):
                    self.feed_model(id)

    def check_for_bids(self):
        with self.auctions_lock:
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
                # Always using default gas price for `deal`
                self._run_future(self.strategy.deal(id).transact_async(gas_price=DefaultGasPrice()))

                # Upon winning a flip or flop auction, we may need to replenish Dai to the Vat.
                # Upon winning a flap auction, we may want to withdraw won Dai from the Vat.
                self.rebalance_dai()

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
            bid_price, bid_transact, cost = self.strategy.bid(id, output.price)
            # If we can't afford the bid, log a warning/error and back out.
            # By continuing, we'll burn through gas fees while the keeper pointlessly retries the bid.
            if cost is not None:
                if not self.check_bid_cost(cost):
                    return

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

    def check_bid_cost(self, cost: Rad) -> bool:
        assert isinstance(cost, Rad)

        # If this is an auction where we bid with Dai...
        if self.flipper or self.flopper:
            vat_dai = self.vat.dai(self.our_address)
            if cost > vat_dai:
                self.logger.warning(f"Bid cost {str(cost)} exceeds vat balance of {vat_dai}; "
                                    "bid will not be submitted")
                return False
            else:
                self.logger.debug(f"Bid cost {str(cost)} is below vat balance of {vat_dai}")
        # If this is an auction where we bid with MKR...
        elif self.flapper:
            mkr_balance = self.mkr.balance_of(self.our_address)
            if cost > Rad(mkr_balance):
                self.logger.warning(f"Bid cost {str(cost)} exceeds MKR balance of {mkr_balance}; "
                                    "bid will not be submitted")
                return False
            else:
                self.logger.debug(f"Bid cost {str(cost)} is below MKR balance of {mkr_balance}")
        return True

    def rebalance_dai(self):
        if self.vat_dai_target is None or not self.dai_join or (not self.flipper and not self.flopper):
            return

        dai = self.dai_join.dai()
        token_balance = dai.balance_of(self.our_address)  # Wad
        difference = Wad(self.vat.dai(self.our_address)) - self.vat_dai_target  # Wad
        if difference < Wad(0):
            # Join tokens to the vat
            if token_balance > difference * -1:
                self.logger.info(f"Joining {str(difference * -1)} Dai to the Vat")
                assert self.dai_join.join(self.our_address, difference * -1).transact()
            elif token_balance > Wad(0):
                self.logger.warning(f"Insufficient balance to maintain Dai target; joining {str(token_balance)} "
                                    "Dai to the Vat")
                assert self.dai_join.join(self.our_address, token_balance).transact()
            else:
                self.logger.warning("No Dai is available to join to Vat; cannot maintain Dai target")
        elif difference > Wad(0):
            # Exit dai from the vat
            self.logger.info(f"Exiting {str(difference)} Dai from the Vat")
            assert self.dai_join.exit(self.our_address, difference).transact()
        self.logger.info(f"Dai token balance: {str(dai.balance_of(self.our_address))}, "
                         f"Vat balance: {self.vat.dai(self.our_address)}")

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
