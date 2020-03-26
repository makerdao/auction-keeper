# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2020 reverendus, bargst, EdNoepel
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
import functools
import logging
import time
import sys
import threading

from datetime import datetime
from requests.exceptions import RequestException
from web3 import Web3, HTTPProvider

from pymaker import Address
from pymaker.approval import hope_directly
from pymaker.deployment import DssDeployment
from pymaker.gas import DefaultGasPrice
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad, Ray, Rad

from auction_keeper.gas import DynamicGasPrice, UpdatableGasPrice
from auction_keeper.logic import Auction, Auctions
from auction_keeper.model import ModelFactory
from auction_keeper.strategy import FlopperStrategy, FlapperStrategy, FlipperStrategy
from auction_keeper.urn_history import UrnHistory


class AuctionKeeper:
    logger = logging.getLogger()

    def __init__(self, args: list, **kwargs):
        parser = argparse.ArgumentParser(prog='auction-keeper')

        parser.add_argument("--rpc-host", type=str, default="http://localhost:8545",
                            help="JSON-RPC endpoint URI with port (default: `http://localhost:8545')")
        parser.add_argument("--rpc-port", type=int, default=8545,
                            help="JSON-RPC port (deprecated) to support legacy configs")
        parser.add_argument("--rpc-timeout", type=int, default=10,
                            help="JSON-RPC timeout (in seconds, default: 10)")

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum account from which to send transactions")
        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=aaa.json,pass_file=aaa.pass')")

        parser.add_argument('--type', type=str, choices=['flip', 'flap', 'flop'],
                            help="Auction type in which to participate")
        parser.add_argument('--ilk', type=str,
                            help="Name of the collateral type for a flip keeper (e.g. 'ETH-B', 'ZRX-A'); "
                                 "available collateral types can be found at the left side of the CDP Portal")

        parser.add_argument('--bid-only', dest='create_auctions', action='store_false',
                            help="Do not take opportunities to create new auctions")
        parser.add_argument('--kick-only', dest='bid_on_auctions', action='store_false',
                            help="Do not bid on auctions")
        parser.add_argument('--deal-for', type=str, nargs="+",
                            help="List of addresses for which auctions will be dealt")

        parser.add_argument('--min-auction', type=int, default=1,
                            help="Lowest auction id to consider")
        parser.add_argument('--max-auctions', type=int, default=1000,
                            help="Maximum number of auctions to simultaneously interact with, "
                                 "used to manage OS and hardware limitations")
        parser.add_argument('--min-flip-lot', type=float, default=0,
                            help="Minimum lot size to create or bid upon a flip auction")
        parser.add_argument('--bid-check-interval', type=float, default=2.0,
                            help="Period of timer used to check bidding models for changes")
        parser.add_argument('--bid-delay', type=float, default=0.0,
                            help="Seconds to wait between bids, used to manage OS and hardware limitations")
        parser.add_argument('--shard-id', type=int, default=0,
                            help="When sharding auctions across multiple keepers, this identifies the shard")
        parser.add_argument('--shards', type=int, default=1,
                            help="Number of shards; should be one greater than your highest --shard-id")

        parser.add_argument("--vulcanize-endpoint", type=str,
                            help="When specified, frob history will be queried from a VulcanizeDB lite node, "
                                 "reducing load on the Ethereum node for flip auctions")
        parser.add_argument('--from-block', type=int,
                            help="Starting block from which to find vaults to bite or debt to queue "
                                 "(set to block where MCD was deployed)")

        parser.add_argument('--vat-dai-target', type=float,
                            help="Amount of Dai to keep in the Vat contract (e.g. 2000)")
        parser.add_argument('--keep-dai-in-vat-on-exit', dest='exit_dai_on_shutdown', action='store_false',
                            help="Retain Dai in the Vat on exit, saving gas when restarting the keeper")
        parser.add_argument('--keep-gem-in-vat-on-exit', dest='exit_gem_on_shutdown', action='store_false',
                            help="Retain collateral in the Vat on exit")

        parser.add_argument("--model", type=str, required=True, nargs='+',
                            help="Commandline to use in order to start the bidding model")

        parser.add_argument("--ethgasstation-api-key", type=str, default=None, help="ethgasstation API key")
        parser.add_argument('--etherchain-gas-price', dest='etherchain_gas', action='store_true',
                            help="Use etherchain.org gas price")
        parser.add_argument('--poanetwork-gas-price', dest='poanetwork_gas', action='store_true',
                            help="Use POANetwork gas price")
        parser.add_argument("--poanetwork-url", type=str, default=None, help="Alternative POANetwork URL")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        # Configure connection to the chain
        if self.arguments.rpc_host.startswith("http"):  # http connection
            provider = HTTPProvider(endpoint_uri=self.arguments.rpc_host,
                                    request_kwargs={'timeout': self.arguments.rpc_timeout})
        else:  # legacy config; separate host and port
            provider = HTTPProvider(endpoint_uri=f"http://{self.arguments.rpc_host}:{self.arguments.rpc_port}",
                                    request_kwargs={'timeout': self.arguments.rpc_timeout})
        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else Web3(provider)
        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        # Check configuration for retrieving urns/bites
        if self.arguments.type == 'flip' and self.arguments.create_auctions \
                and self.arguments.from_block is None and self.arguments.vulcanize_endpoint is None:
            raise RuntimeError("Either --from-block or --vulcanize-endpoint must be specified to kick off "
                               "flip auctions")
        if self.arguments.type == 'flip' and not self.arguments.ilk:
            raise RuntimeError("--ilk must be supplied when configuring a flip keeper")
        if self.arguments.type == 'flop' and self.arguments.create_auctions \
                and self.arguments.from_block is None:
            raise RuntimeError("--from-block must be specified to kick off flop auctions")

        # Configure core and token contracts
        self.mcd = DssDeployment.from_node(web3=self.web3)
        self.vat = self.mcd.vat
        self.cat = self.mcd.cat
        self.vow = self.mcd.vow
        self.mkr = self.mcd.mkr
        self.dai_join = self.mcd.dai_adapter
        if self.arguments.type == 'flip':
            self.collateral = self.mcd.collaterals[self.arguments.ilk]
            self.ilk = self.collateral.ilk
            self.gem_join = self.collateral.adapter
        else:
            self.collateral = None
            self.ilk = None
            self.gem_join = None

        # Configure auction contracts
        self.flipper = self.collateral.flipper if self.arguments.type == 'flip' else None
        self.flapper = self.mcd.flapper if self.arguments.type == 'flap' else None
        self.flopper = self.mcd.flopper if self.arguments.type == 'flop' else None
        self.urn_history = None
        if self.flipper:
            self.min_flip_lot = Wad.from_number(self.arguments.min_flip_lot)
            self.strategy = FlipperStrategy(self.flipper, self.min_flip_lot)
            self.urn_history = UrnHistory(self.web3, self.mcd, self.ilk, self.arguments.from_block,
                                          self.arguments.vulcanize_endpoint)
        elif self.flapper:
            self.strategy = FlapperStrategy(self.flapper, self.mkr.address)
        elif self.flopper:
            self.strategy = FlopperStrategy(self.flopper)
        else:
            raise RuntimeError("Please specify auction type")

        # Create the collection used to manage auctions relevant to this keeper
        self.auctions = Auctions(flipper=self.flipper.address if self.flipper else None,
                                 flapper=self.flapper.address if self.flapper else None,
                                 flopper=self.flopper.address if self.flopper else None,
                                 model_factory=ModelFactory(' '.join(self.arguments.model)))
        self.auctions_lock = threading.Lock()
        self.dead_auctions = set()
        self.lifecycle = None

        # Create gas strategy used for non-bids
        self.gas_price = DynamicGasPrice(self.arguments)

        self.vat_dai_target = Wad.from_number(self.arguments.vat_dai_target) if \
            self.arguments.vat_dai_target is not None else None

        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))

        # Configure account(s) for which we'll deal auctions
        self.deal_all = False
        self.deal_for = set()
        if self.arguments.deal_for is None:
            self.deal_for.add(self.our_address)
        elif len(self.arguments.deal_for) == 1 and self.arguments.deal_for[0].upper() in ["ALL", "NONE"]:
            if self.arguments.deal_for[0].upper() == "ALL":
                self.deal_all = True
            # else no auctions will be dealt
        elif len(self.arguments.deal_for) > 0:
            for account in self.arguments.deal_for:
                self.deal_for.add(Address(account))

        # reduce logspew
        logging.getLogger('urllib3').setLevel(logging.INFO)
        logging.getLogger("web3").setLevel(logging.INFO)
        logging.getLogger("asyncio").setLevel(logging.INFO)
        logging.getLogger("requests").setLevel(logging.INFO)

    def main(self):
        def seq_func(check_func: callable):
            assert callable(check_func)

            # Kick off new auctions
            if self.arguments.create_auctions:
                try:
                    check_func()
                except (RequestException, ConnectionError, ValueError, AttributeError):
                    logging.exception("Error checking for opportunities to start an auction")

            # Bid on and deal existing auctions
            try:
                self.check_all_auctions()
            except (RequestException, ConnectionError, ValueError, AttributeError):
                logging.exception("Error checking auction states")

        with Lifecycle(self.web3) as lifecycle:
            self.lifecycle = lifecycle
            lifecycle.on_startup(self.startup)
            lifecycle.on_shutdown(self.shutdown)
            if self.flipper and self.cat:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_cdps))
            elif self.flapper and self.vow:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_flap))
            elif self.flopper and self.vow:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_flop))
            else:  # unusual corner case
                lifecycle.on_block(self.check_all_auctions)

            if self.arguments.bid_on_auctions:
                lifecycle.every(self.arguments.bid_check_interval, self.check_for_bids)

    def startup(self):
        self.approve()
        self.rebalance_dai()
        if self.flapper:
            self.logger.info(f"MKR balance is {self.mkr.balance_of(self.our_address)}")

        if not self.arguments.create_auctions:
            logging.info("Keeper will not create new auctions")
        if not self.arguments.bid_on_auctions:
            logging.info("Keeper will not bid on auctions")

        if self.deal_all:
            logging.info("Keeper will deal auctions for any address")
        elif len(self.deal_for) == 1:
            logging.info(f"Keeper will deal auctions for {list(self.deal_for)[0].address}")
        elif len(self.deal_for) > 0:
            logging.info(f"Keeper will deal auctions for {self.deal_for} addresses")
        else:
            logging.info("Keeper will not deal auctions")

    def approve(self):
        self.strategy.approve(gas_price=self.gas_price)
        time.sleep(2)
        if self.dai_join:
            self.mcd.approve_dai(usr=self.our_address, gas_price=self.gas_price)

    def shutdown(self):
        with self.auctions_lock:
            del self.auctions
        self.exit_dai_on_shutdown()
        self.exit_collateral_on_shutdown()

    def is_shutting_down(self) -> bool:
        return self.lifecycle and self.lifecycle.terminated_externally

    def exit_dai_on_shutdown(self):
        if not self.arguments.exit_dai_on_shutdown or not self.dai_join:
            return

        vat_balance = Wad(self.vat.dai(self.our_address))
        if vat_balance > Wad(0):
            self.logger.info(f"Exiting {str(vat_balance)} Dai from the Vat before shutdown")
            assert self.dai_join.exit(self.our_address, vat_balance).transact(gas_price=self.gas_price)

    def exit_collateral_on_shutdown(self):
        if not self.arguments.exit_gem_on_shutdown or not self.gem_join:
            return

        vat_balance = self.vat.gem(self.ilk, self.our_address)
        if vat_balance > Wad(0):
            self.logger.info(f"Exiting {str(vat_balance)} {self.ilk.name} from the Vat before shutdown")
            assert self.gem_join.exit(self.our_address, vat_balance).transact(gas_price=self.gas_price)

    def auction_handled_by_this_shard(self, id: int) -> bool:
        assert isinstance(id, int)
        if id % self.arguments.shards == self.arguments.shard_id:
            return True
        else:
            logging.debug(f"Auction {id} is not handled by shard {self.arguments.shard_id}")
            return False

    def check_cdps(self):
        started = datetime.now()
        ilk = self.vat.ilk(self.ilk.name)
        rate = ilk.rate
        dai_to_bid = self.vat.dai(self.our_address)

        # Look for unsafe CDPs and bite them
        urns = self.urn_history.get_urns()
        for urn in urns.values():
            safe = urn.ink * ilk.spot >= urn.art * rate
            if not safe:
                if self.arguments.bid_on_auctions and dai_to_bid == Rad(0):
                    self.logger.warning(f"Skipping opportunity to bite urn {urn.address} "
                                        "because there is no Dai to bid")
                    break

                if urn.ink < self.min_flip_lot:
                    self.logger.info(f"Ignoring urn {urn.address.address} with ink={urn.ink} < "
                                     f"min_lot={self.min_flip_lot}")
                    continue

                self._run_future(self.cat.bite(ilk, urn).transact_async(gas_price=self.gas_price))

        self.logger.debug(f"Checked {len(urns)} urns in {(datetime.now()-started).seconds} seconds")
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

                if self.arguments.bid_on_auctions and self.mkr.balance_of(self.our_address) == Wad(0):
                    self.logger.warning("Skipping opportunity to heal/flap because there is no MKR to bid")
                    return

                woe = self.vow.woe()
                # Heal the system to bring Woe to 0
                if woe > Rad(0):
                    self.vow.heal(woe).transact(gas_price=self.gas_price)
                self.vow.flap().transact(gas_price=self.gas_price)

    def reconcile_debt(self, joy: Rad, ash: Rad, woe: Rad):
        assert isinstance(joy, Rad)
        assert isinstance(ash, Rad)
        assert isinstance(woe, Rad)

        if ash > Rad(0):
            if joy > ash:
                self.vow.kiss(ash).transact(gas_price=self.gas_price)
            else:
                self.vow.kiss(joy).transact(gas_price=self.gas_price)
                return
        if woe > Rad(0):
            joy = self.vat.dai(self.vow.address)
            if joy > woe:
                self.vow.heal(woe).transact(gas_price=self.gas_price)
            else:
                self.vow.heal(joy).transact(gas_price=self.gas_price)

    def check_flop(self):
        # Check if Vow has a surplus of bad debt compared to Dai
        joy = self.vat.dai(self.vow.address)
        awe = self.vat.sin(self.vow.address)

        # Check if Vow has bad debt in excess
        excess_debt = joy < awe
        if not excess_debt:
            return

        woe = self.vow.woe()
        sin = self.vow.sin()
        sump = self.vow.sump()
        wait = self.vow.wait()

        # Check if Vow has enough bad debt to start an auction and that we have enough dai balance
        if woe + sin >= sump:
            # We need to bring Joy to 0 and Woe to at least sump

            if self.arguments.bid_on_auctions and self.vat.dai(self.our_address) == Rad(0):
                self.logger.warning("Skipping opportunity to kiss/flog/heal/flop because there is no Dai to bid")
                return

            # first use kiss() as it settled bad debt already in auctions and doesn't decrease woe
            ash = self.vow.ash()
            if joy > Rad(0):
                self.reconcile_debt(joy, ash, woe)

            # Convert enough sin in woe to have woe >= sump + joy
            if woe < (sump + joy) and self.cat is not None:
                past_blocks = self.web3.eth.blockNumber - self.arguments.from_block
                for bite_event in self.cat.past_bites(past_blocks):  # TODO: cache ?
                    era = bite_event.era(self.web3)
                    now = self.web3.eth.getBlock('latest')['timestamp']
                    sin = self.vow.sin_of(era)
                    # If the bite hasn't already been flogged and has aged past the `wait`
                    if sin > Rad(0) and era + wait <= now:
                        self.vow.flog(era).transact(gas_price=self.gas_price)

                        # flog() sin until woe is above sump + joy
                        joy = self.vat.dai(self.vow.address)
                        if self.vow.woe() - joy >= sump:
                            break

            # Reduce on-auction debt and reconcile remaining joy
            joy = self.vat.dai(self.vow.address)
            if joy > Rad(0):
                ash = self.vow.ash()
                woe = self.vow.woe()
                self.reconcile_debt(joy, ash, woe)
                joy = self.vat.dai(self.vow.address)

            woe = self.vow.woe()
            if sump <= woe and joy == Rad(0):
                self.vow.flop().transact(gas_price=self.gas_price)

    def check_all_auctions(self):
        started = datetime.now()
        for id in range(self.arguments.min_auction, self.strategy.kicks() + 1):
            if not self.auction_handled_by_this_shard(id):
                continue
            with self.auctions_lock:
                # If we're exiting, release the lock around checking auctions
                if self.is_shutting_down():
                    return

                # Check whether auction needs to be handled; deal the auction if appropriate
                if not self.check_auction(id):
                    continue

                # If we're not bidding, don't produce a price model for the auction
                if not self.arguments.bid_on_auctions:
                    continue

                # Prevent growing the auctions collection beyond the configured size
                if len(self.auctions.auctions) < self.arguments.max_auctions:
                    self.feed_model(id)
                else:
                    logging.warning(f"Processing {len(self.auctions.auctions)} auctions; ignoring auction {id}")

        self.logger.debug(f"Checked {self.strategy.kicks()} auctions in {(datetime.now() - started).seconds} seconds")

    def check_for_bids(self):
        with self.auctions_lock:
            for id, auction in self.auctions.auctions.items():
                # If we're exiting, release the lock around checking price models
                if self.is_shutting_down():
                    return

                if not self.auction_handled_by_this_shard(id):
                    continue
                self.handle_bid(id=id, auction=auction)

    # TODO if we will introduce multithreading here, proper locking should be introduced as well
    #     locking should not happen on `auction.lock`, but on auction.id here. as sometimes we will
    #     intend to lock on auction id but not create `Auction` object for it (as the auction is already finished
    #     for example).
    def check_auction(self, id: int) -> bool:
        assert isinstance(id, int)

        # Improves performance by avoiding an onchain call to check auctions we know have completed.
        if id in self.dead_auctions:
            return False

        # Read auction information from the chain
        input = self.strategy.get_input(id)
        auction_missing = (input.end == 0)
        auction_finished = (input.tic < input.era and input.tic != 0) or (input.end < input.era)
        logging.debug(f"Auction {id} missing={auction_missing}, finished={auction_finished}")

        if auction_missing:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            self.dead_auctions.add(id)
            return False

        # Check if the auction is finished.  If so configured, `deal` the auction.
        elif auction_finished:
            if self.deal_all or input.guy in self.deal_for:
                # Always using default gas price for `deal`
                self._run_future(self.strategy.deal(id).transact_async(gas_price=self.gas_price))

                # Upon winning a flip or flop auction, we may need to replenish Dai to the Vat.
                # Upon winning a flap auction, we may want to withdraw won Dai from the Vat.
                self.rebalance_dai()

            # Remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            self.dead_auctions.add(id)
            return False

        else:
            return True

    def feed_model(self, id: int):
        assert isinstance(id, int)

        # Create or get the price model associated with the auction
        auction = self.auctions.get_auction(id)

        # Read auction state from the chain
        input = self.strategy.get_input(id)

        # Feed the model with current state
        auction.feed_model(input)

    def handle_bid(self, id: int, auction: Auction):
        assert isinstance(id, int)
        assert isinstance(auction, Auction)

        output = auction.model_output()

        if output is None:
            return

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
                if self.arguments.bid_delay:
                    logging.debug(f"Waiting {self.arguments.bid_delay}s")
                    time.sleep(self.arguments.bid_delay)

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
                self.logger.debug(f"Bid cost {str(cost)} exceeds vat balance of {vat_dai}; "
                                  "bid will not be submitted")
                return False
        # If this is an auction where we bid with MKR...
        elif self.flapper:
            mkr_balance = self.mkr.balance_of(self.our_address)
            if cost > Rad(mkr_balance):
                self.logger.debug(f"Bid cost {str(cost)} exceeds MKR balance of {mkr_balance}; "
                                  "bid will not be submitted")
                return False
        return True

    def rebalance_dai(self):
        if self.vat_dai_target is None or not self.dai_join or (not self.flipper and not self.flopper):
            return

        dai = self.dai_join.dai()
        token_balance = dai.balance_of(self.our_address)  # Wad
        difference = Wad(self.vat.dai(self.our_address)) - self.vat_dai_target  # Wad
        if difference < Wad(0):
            # Join tokens to the vat
            if token_balance >= difference * -1:
                self.logger.info(f"Joining {str(difference * -1)} Dai to the Vat")
                assert self.dai_join.join(self.our_address, difference * -1).transact(gas_price=self.gas_price)
            elif token_balance > Wad(0):
                self.logger.warning(f"Insufficient balance to maintain Dai target; joining {str(token_balance)} "
                                    "Dai to the Vat")
                assert self.dai_join.join(self.our_address, token_balance).transact(gas_price=self.gas_price)
            else:
                self.logger.warning("No Dai is available to join to Vat; cannot maintain Dai target")
        elif difference > Wad(0):
            # Exit dai from the vat
            self.logger.info(f"Exiting {str(difference)} Dai from the Vat")
            assert self.dai_join.exit(self.our_address, difference).transact(gas_price=self.gas_price)
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
