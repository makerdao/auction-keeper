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
from typing import Optional
from web3 import Web3

from pymaker import Address, get_pending_transactions, web3_via_http
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.model import Token
from pymaker.numeric import Wad, Ray, Rad

from auction_keeper.gas import DynamicGasPrice, UpdatableGasPrice
from auction_keeper.logic import Auction, Auctions, Reservoir
from auction_keeper.model import ModelFactory
from auction_keeper.strategy import FlopperStrategy, FlapperStrategy, FlipperStrategy
from auction_keeper.urn_history import ChainUrnHistoryProvider
from auction_keeper.urn_history_tokenflow import TokenFlowUrnHistoryProvider
from auction_keeper.urn_history_vulcanize import VulcanizeUrnHistoryProvider


class AuctionKeeper:
    logger = logging.getLogger()
    dead_after = 10  # Assume block reorgs cannot resurrect an auction id after this many blocks

    def __init__(self, args: list, **kwargs):
        parser = argparse.ArgumentParser(prog='auction-keeper')

        parser.add_argument("--rpc-host", type=str, default="http://localhost:8545",
                            help="JSON-RPC endpoint URI with port (default: `http://localhost:8545')")
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
                                 "available collateral types can be found at the left side of the Oasis Borrow")

        parser.add_argument('--bid-only', dest='create_auctions', action='store_false',
                            help="Do not take opportunities to create new auctions")
        parser.add_argument('--kick-only', dest='bid_on_auctions', action='store_false',
                            help="Do not bid on auctions")
        parser.add_argument('--deal-for', type=str, nargs="+",
                            help="List of addresses for which auctions will be dealt")

        parser.add_argument('--min-auction', type=int, default=0,
                            help="Lowest auction id to consider")
        parser.add_argument('--max-auctions', type=int, default=1000,
                            help="Maximum number of auctions to simultaneously interact with, "
                                 "used to manage OS and hardware limitations")
        parser.add_argument('--min-flip-lot', type=float, default=0,
                            help="Minimum lot size to create or bid upon a flip auction")
        parser.add_argument('--bid-check-interval', type=float, default=4.0,
                            help="Period of timer [in seconds] used to check bidding models for changes")
        parser.add_argument('--bid-delay', type=float, default=0.0,
                            help="Seconds to wait between bids, used to manage OS and hardware limitations")
        parser.add_argument('--shard-id', type=int, default=0,
                            help="When sharding auctions across multiple keepers, this identifies the shard")
        parser.add_argument('--shards', type=int, default=1,
                            help="Number of shards; should be one greater than your highest --shard-id")

        parser.add_argument('--from-block', type=int,
                            help="Starting block from which to find vaults to bite or debt to queue "
                                 "(set to block where MCD was deployed)")
        parser.add_argument('--chunk-size', type=int, default=20000,
                            help="When batching chain history requests, this is the number of blocks for each request")
        parser.add_argument("--tokenflow-url", type=str,
                            help="When specified, urn history will be initialized using the TokenFlow API")
        parser.add_argument("--tokenflow-key", type=str, help="API key for the TokenFlow endpoint")
        parser.add_argument("--vulcanize-endpoint", type=str,
                            help="When specified, urn history will be initialized from a VulcanizeDB node")
        parser.add_argument("--vulcanize-key", type=str, help="API key for the Vulcanize endpoint")

        parser.add_argument('--vat-dai-target', type=str,
                            help="Amount of Dai to keep in the Vat contract or ALL to join entire token balance")
        parser.add_argument('--keep-dai-in-vat-on-exit', dest='exit_dai_on_shutdown', action='store_false',
                            help="Retain Dai in the Vat on exit, saving gas when restarting the keeper")
        parser.add_argument('--keep-gem-in-vat-on-exit', dest='exit_gem_on_shutdown', action='store_false',
                            help="Retain collateral in the Vat on exit")
        parser.add_argument('--return-gem-interval', type=int, default=300,
                            help="Period of timer [in seconds] used to check and exit won collateral")

        parser.add_argument("--model", type=str, nargs='+',
                            help="Commandline to use in order to start the bidding model")

        parser.add_argument("--oracle-gas-price", action='store_true',
                            help="Use a fast gas price aggregated across multiple oracles")
        parser.add_argument("--ethgasstation-api-key", type=str, default=None, help="ethgasstation API key")
        parser.add_argument("--etherscan-api-key", type=str, default=None, help="etherscan API key")
        parser.add_argument('--fixed-gas-price', type=float, default=None,
                            help="Uses a fixed value (in Gwei) instead of an external API to determine initial gas")
        parser.add_argument("--poanetwork-url", type=str, default=None, help="Alternative POANetwork URL")
        parser.add_argument("--gas-initial-multiplier", type=float, default=1.0,
                            help="Adjusts the initial API-provided 'fast' gas price, default 1.0")
        parser.add_argument("--gas-reactive-multiplier", type=float, default=1.125,
                            help="Increases gas price when transactions haven't been mined after some time")
        parser.add_argument("--gas-maximum", type=float, default=2000,
                            help="Places an upper bound (in Gwei) on the amount of gas to use for a single TX")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        # Configure connection to the chain
        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else web3_via_http(
            endpoint_uri=self.arguments.rpc_host, timeout=self.arguments.rpc_timeout, http_pool_size=100)
        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        # Check configuration for retrieving urns/bites
        if self.arguments.type == 'flip' and self.arguments.create_auctions \
                and self.arguments.from_block is None \
                and self.arguments.tokenflow_url is None \
                and self.arguments.vulcanize_endpoint is None:
            raise RuntimeError("One of --from-block, --tokenflow_url, or --vulcanize-endpoint must be specified "
                               "to bite and kick off new flip auctions")
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
            if self.arguments.create_auctions:
                if self.arguments.vulcanize_endpoint:
                    self.urn_history = VulcanizeUrnHistoryProvider(self.mcd, self.ilk,
                                                                   self.arguments.vulcanize_endpoint,
                                                                   self.arguments.vulcanize_key)
                elif self.arguments.tokenflow_url:
                    self.urn_history = TokenFlowUrnHistoryProvider(self.web3, self.mcd, self.ilk,
                                                                   self.arguments.tokenflow_url,
                                                                   self.arguments.chunk_size)
                else:
                    self.urn_history = ChainUrnHistoryProvider(self.web3, self.mcd, self.ilk,
                                                               self.arguments.from_block, self.arguments.chunk_size)

        elif self.flapper:
            self.strategy = FlapperStrategy(self.flapper, self.mkr.address)
        elif self.flopper:
            self.strategy = FlopperStrategy(self.flopper)
        else:
            raise RuntimeError("Please specify auction type")

        # Create the collection used to manage auctions relevant to this keeper
        if self.arguments.model:
            model_command = ' '.join(self.arguments.model)
        else:
            if self.arguments.bid_on_auctions:
                raise RuntimeError("--model must be specified to bid on auctions")
            else:
                model_command = ":"
        self.auctions = Auctions(flipper=self.flipper.address if self.flipper else None,
                                 flapper=self.flapper.address if self.flapper else None,
                                 flopper=self.flopper.address if self.flopper else None,
                                 model_factory=ModelFactory(model_command))
        self.auctions_lock = threading.Lock()
        # Since we don't want periodically-pollled bidding threads to back up, use a flag instead of a lock.
        self.is_joining_dai = False
        self.dead_since = {}
        self.lifecycle = None

        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))

        # Create gas strategy used for non-bids and bids which do not supply gas price
        self.gas_price = DynamicGasPrice(self.arguments, self.web3)

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
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_vaults))
            elif self.flapper and self.vow:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_flap))
            elif self.flopper and self.vow:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_flop))
            else:  # unusual corner case
                lifecycle.on_block(self.check_all_auctions)

            if self.arguments.bid_on_auctions:
                lifecycle.every(self.arguments.bid_check_interval, self.check_for_bids)
            if self.arguments.return_gem_interval:
                lifecycle.every(self.arguments.return_gem_interval, self.exit_gem)

    def auction_notice(self) -> str:
        if self.arguments.type == 'flip':
            return "--> Check all urns and kick off new auctions if any" + \
                   " unsafe urns need to be bitten"
        else:
            return "--> Check thresholds in Vow Contract and kick off new" + \
                  f" {self.arguments.type} auctions once reached"

    def startup(self):
        self.plunge()
        self.approve()
        self.rebalance_dai()
        if self.flapper:
            self.logger.info(f"MKR balance is {self.mkr.balance_of(self.our_address)}")

        notice_string = []
        if not self.arguments.create_auctions:
            logging.info("Keeper will not create new auctions")
        else:
            notice_string.append(self.auction_notice())
        if not self.arguments.bid_on_auctions:
            logging.info("Keeper will not bid on auctions")
        else:
            notice_string.append("--> Check all auctions being monitored and evaluate" + \
                                f" bidding opportunity every {self.arguments.bid_check_interval} seconds")

        if self.deal_all:
            notice_string.append("--> Check all auctions and deal for any address")
        elif len(self.deal_for) == 1:
            notice_string.append(f"--> Check all auctions and deal for {list(self.deal_for)[0].address}")
        elif len(self.deal_for) > 0:
            notice_string.append(f"--> Check all auctions and deal for {[a.address for a in self.deal_for]} addresses")
        else:
            logging.info("Keeper will not deal auctions")

        if notice_string:
            logging.info("Keeper will perform the following operation(s) in parallel:")
            [logging.info(line) for line in notice_string]

            if self.flipper and self.ilk and self.ilk.name == "ETH-A":
                logging.info("*** When Keeper is dealing/bidding, the initial evaluation of auctions will likely take > 45 minutes without setting a lower boundary via '--min-auction' ***")
                logging.info("*** When Keeper is kicking, initializing urn history may take > 30 minutes without using VulcanizeDB via `--vulcanize-endpoint` ***")
        else:
            logging.info("Keeper is currently inactive. Consider re-running the startup script with --bid-only or --kick-only")

        logging.info(f"Keeper will use {self.gas_price} for transactions and bids unless model instructs otherwise")

    def approve(self):
        self.strategy.approve(gas_price=self.gas_price)
        time.sleep(1)
        if self.dai_join:
            if self.mcd.dai.allowance_of(self.our_address, self.dai_join.address) > Wad.from_number(2**50):
                return
            else:
                self.mcd.approve_dai(usr=self.our_address, gas_price=self.gas_price)
        time.sleep(1)
        if self.collateral:
            self.collateral.approve(self.our_address, gas_price=self.gas_price)

    def plunge(self):
        pending_txes = get_pending_transactions(self.web3)
        if len(pending_txes) > 0:
            while len(pending_txes) > 0:
                logging.warning(f"Cancelling first of {len(pending_txes)} pending transactions")
                pending_txes[0].cancel(gas_price=self.gas_price)
                # After the synchronous cancel, wait to see if subsequent transactions get mined
                time.sleep(28)
                pending_txes = get_pending_transactions(self.web3)

    def shutdown(self):
        with self.auctions_lock:
            del self.auctions
        if self.arguments.exit_dai_on_shutdown:
            self.exit_dai_on_shutdown()
        if not self.arguments.exit_gem_on_shutdown:
            self.exit_gem()

    def is_shutting_down(self) -> bool:
        return self.lifecycle and self.lifecycle.terminated_externally

    def exit_dai_on_shutdown(self):
        # Unlike rebalance_dai(), this doesn't join, and intentionally doesn't check dust
        vat_balance = Wad(self.vat.dai(self.our_address))
        if vat_balance > Wad(0):
            self.logger.info(f"Exiting {str(vat_balance)} Dai from the Vat before shutdown")
            assert self.dai_join.exit(self.our_address, vat_balance).transact(gas_price=self.gas_price)

    def auction_handled_by_this_shard(self, id: int) -> bool:
        assert isinstance(id, int)
        if id % self.arguments.shards == self.arguments.shard_id:
            return True
        else:
            logging.debug(f"Auction {id} is not handled by shard {self.arguments.shard_id}")
            return False

    def can_bite(self, ilk: Ilk, urn: Urn, box: Rad, dunk: Rad, chop: Wad) -> bool:
        # Typechecking intentionally omitted to improve performance
        rate = ilk.rate

        # Collateral value should be less than the product of our stablecoin debt and the debt multiplier
        safe = Ray(urn.ink) * ilk.spot >= Ray(urn.art) * rate
        if safe:
            return False

        # Ensure there's room in the litter box
        litter = self.cat.litter()
        room: Rad = box - litter
        if litter >= box:
            return False
        if room < ilk.dust:
            return False

        # Prevent null auction (ilk.dunk [Rad], ilk.rate [Ray], ilk.chop [Wad])
        dart: Wad = min(urn.art, Wad(min(dunk, room) / Rad(ilk.rate) / Rad(chop)))
        dink: Wad = min(urn.ink, urn.ink * dart / urn.art)
        return dart > Wad(0) and dink > Wad(0)

    def check_vaults(self):
        started = datetime.now()
        available_dai = self.mcd.dai.balance_of(self.our_address) + Wad(self.vat.dai(self.our_address))
        box = self.cat.box()
        dunk = self.cat.dunk(self.ilk)
        chop = self.cat.chop(self.ilk)

        if not self.collateral.flipper.wards(self.mcd.cat.address):
            self.logger.warning(f"Cat is not authorized to kick on this flipper")
            return

        # Look for unsafe vaults and bite them
        urns = self.urn_history.get_urns()
        logging.debug(f"Evaluating {len(urns)} {self.ilk} urns to be bitten if any are unsafe")

        for i, urn in enumerate(urns.values()):
            if i % 500 == 0:  # Every 500 vaults, free some CPU and then update ilk.rate
                if self.is_shutting_down():
                    return
                time.sleep(1)
                ilk = self.vat.ilk(self.ilk.name)  # ilk.rate changes every block

            if self.can_bite(ilk, urn, box, dunk, chop):
                if self.arguments.bid_on_auctions and available_dai == Wad(0):
                    self.logger.warning(f"Skipping opportunity to bite urn {urn.address} "
                                        "because there is no Dai to bid")
                    break

                if urn.ink < self.min_flip_lot:
                    self.logger.info(f"Ignoring urn {urn.address.address} with ink={urn.ink} < "
                                     f"min_lot={self.min_flip_lot}")
                    continue

                self.cat.bite(ilk, urn).transact(gas_price=self.gas_price)

        self.logger.info(f"Checked {len(urns)} urns in {(datetime.now()-started).seconds} seconds")
        # Cat.bite implicitly kicks off the flip auction; no further action needed.

    def check_flap(self):
        # Check if Vow has a surplus of Dai compared to bad debt
        joy = self.vat.dai(self.vow.address)
        awe = self.vat.sin(self.vow.address)

        if not self.flapper.wards(self.mcd.vow.address):
            self.logger.warning(f"Vow is not authorized to kick on this flapper")
            return

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

        if not self.flopper.wards(self.mcd.vow.address):
            self.logger.warning(f"Vow is not authorized to kick on this flopper")
            return

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

            available_dai = self.mcd.dai.balance_of(self.our_address) + Wad(self.vat.dai(self.our_address))
            if self.arguments.bid_on_auctions and available_dai == Wad(0):
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
        ignored_auctions = []

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
                elif id not in self.auctions.auctions.keys():
                    ignored_auctions.append(id)

        if len(ignored_auctions) > 0:
            logging.warning(f"Processing auctions {list(self.auctions.auctions.keys())}; ignoring {ignored_auctions}")

        self.logger.info(f"Checked auctions {self.arguments.min_auction} to {self.strategy.kicks()} in " 
                         f"{(datetime.now() - started).seconds} seconds")

    def check_for_bids(self):
        # Initialize the reservoir with Dai/MKR balance for this round of bid submissions.
        # This isn't a perfect solution as it omits the cost of bids submitted from the last round.
        # Recreating the reservoir preserves the stateless design of this keeper.
        if self.flipper or self.flopper:
            reservoir = Reservoir(self.vat.dai(self.our_address))
        elif self.flapper:
            reservoir = Reservoir(Rad(self.mkr.balance_of(self.our_address)))
        else:
            raise RuntimeError("Unsupported auction type")
        
        with self.auctions_lock:
            for id, auction in self.auctions.auctions.items():
                # If we're exiting, release the lock around checking price models
                if self.is_shutting_down():
                    return

                if not self.auction_handled_by_this_shard(id):
                    continue
                self.handle_bid(id=id, auction=auction, reservoir=reservoir)

    # TODO if we will introduce multithreading here, proper locking should be introduced as well
    #     locking should not happen on `auction.lock`, but on auction.id here. as sometimes we will
    #     intend to lock on auction id but not create `Auction` object for it (as the auction is already finished
    #     for example).
    def check_auction(self, id: int) -> bool:
        assert isinstance(id, int)
        current_block = self.web3.eth.blockNumber
        assert isinstance(current_block, int)

        # Improves performance by avoiding an onchain call to check auctions we know have completed.
        if id in self.dead_since and current_block - self.dead_since[id] > 10:
            return False

        # Read auction information from the chain
        input = self.strategy.get_input(id)
        auction_deleted = (input.end == 0)
        auction_finished = (input.tic < input.era and input.tic != 0) or (input.end < input.era)

        if auction_deleted:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            self.dead_since[id] = current_block
            logging.debug(f"Stopped tracking auction {id}")
            return False

        # Check if the auction is finished.  If so configured, `tick` or `deal` the auction synchronously.
        elif auction_finished:
            if input.tic == 0:
                if self.arguments.create_auctions:
                    logging.info(f"Auction {id} ended without bids; resurrecting auction")
                    self.strategy.tick(id).transact(gas_price=self.gas_price)
                    return True
            elif self.deal_all or input.guy in self.deal_for:
                self.strategy.deal(id).transact(gas_price=self.gas_price)

                # Upon winning a flip or flop auction, we may need to replenish Dai to the Vat.
                # Upon winning a flap auction, we may want to withdraw won Dai from the Vat.
                self.rebalance_dai()
            else:
                logging.debug(f"Not dealing {id} with guy={input.guy}")

            # Remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            self.dead_since[id] = current_block
            logging.debug(f"Auction {id} finished")
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

    def handle_bid(self, id: int, auction: Auction, reservoir: Reservoir):
        assert isinstance(id, int)
        assert isinstance(auction, Auction)
        assert isinstance(reservoir, Reservoir)

        output = auction.model_output()
        if output is None:
            return

        bid_price, bid_transact, cost = self.strategy.bid(id, output.price)
        # If we can't afford the bid, log a warning/error and back out.
        # By continuing, we'll burn through gas fees while the keeper pointlessly retries the bid.
        if cost is not None:
            if not self.check_bid_cost(id, cost, reservoir):
                return

        if bid_price is not None and bid_transact is not None:
            assert isinstance(bid_price, Wad)
            # Ensure this auction has a gas strategy assigned
            (new_gas_strategy, fixed_gas_price_changed) = auction.determine_gas_strategy_for_bid(output, self.gas_price)

            # if no transaction in progress, send a new one
            transaction_in_progress = auction.transaction_in_progress()

            logging.debug(f"Handling bid for auction {id}: tx in progress={transaction_in_progress is not None}, " 
                          f"auction.price={auction.price}, bid_price={bid_price}")

            # if transaction has not been submitted...
            if transaction_in_progress is None:
                self.logger.info(f"Sending new bid @{output.price} for auction {id}")
                auction.price = bid_price
                auction.gas_price = new_gas_strategy if new_gas_strategy else auction.gas_price
                auction.register_transaction(bid_transact)

                # ...submit a new transaction and wait the delay period (if so configured)
                self._run_future(bid_transact.transact_async(gas_price=auction.gas_price))
                if self.arguments.bid_delay:
                    logging.debug(f"Waiting {self.arguments.bid_delay}s")
                    time.sleep(self.arguments.bid_delay)

            # if transaction in progress and the bid price changed...
            elif auction.price and bid_price != auction.price:
                self.logger.info(f"Attempting to override pending bid with new bid @{output.price} for auction {id}")
                auction.price = bid_price
                if new_gas_strategy:  # gas strategy changed
                    auction.gas_price = new_gas_strategy
                elif fixed_gas_price_changed:  # gas price updated
                    assert isinstance(auction.gas_price, UpdatableGasPrice)
                    auction.gas_price.update_gas_price(output.gas_price)
                auction.register_transaction(bid_transact)

                # ...ask pymaker to replace the transaction
                self._run_future(bid_transact.transact_async(replace=transaction_in_progress,
                                                             gas_price=auction.gas_price))

            # if model has been providing a gas price, and only that changed...
            elif fixed_gas_price_changed:
                assert isinstance(auction.gas_price, UpdatableGasPrice)
                self.logger.info(f"Overriding pending bid with new gas_price ({output.gas_price}) for auction {id}")
                auction.gas_price.update_gas_price(output.gas_price)

            # if transaction in progress, bid price unchanged, but gas strategy changed...
            elif new_gas_strategy:
                self.logger.info(f"Changing gas strategy for pending bid @{output.price} for auction {id}")
                auction.price = bid_price
                auction.gas_price = new_gas_strategy
                auction.register_transaction(bid_transact)

                # ...ask pymaker to replace the transaction
                self._run_future(bid_transact.transact_async(replace=transaction_in_progress,
                                                             gas_price=auction.gas_price))

    def check_bid_cost(self, id: int, cost: Rad, reservoir: Reservoir, already_rebalanced=False) -> bool:
        assert isinstance(id, int)
        assert isinstance(cost, Rad)

        # If this is an auction where we bid with Dai...
        if self.flipper or self.flopper:
            if not reservoir.check_bid_cost(id, cost):
                if not already_rebalanced:
                    # Try to synchronously join Dai the Vat
                    if self.is_joining_dai:
                        self.logger.info(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                          "waiting for Dai to rebalance")
                        return False
                    else:
                        rebalanced = self.rebalance_dai()
                        if rebalanced and rebalanced > Wad(0):
                            reservoir.refill(Rad(rebalanced))
                            return self.check_bid_cost(id, cost, reservoir, already_rebalanced=True)

                self.logger.info(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                  "bid will not be submitted")
                return False
        # If this is an auction where we bid with MKR...
        elif self.flapper:
            mkr_balance = self.mkr.balance_of(self.our_address)
            if cost > Rad(mkr_balance):
                self.logger.debug(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                  "bid will not be submitted")
                return False
        return True

    def rebalance_dai(self) -> Optional[Wad]:
        # Returns amount joined (positive) or exited (negative) as a result of rebalancing towards vat_dai_target

        if self.arguments.vat_dai_target is None:
            return None

        logging.info(f"Checking if internal Dai balance needs to be rebalanced")
        dai = self.dai_join.dai()
        token_balance = dai.balance_of(self.our_address)  # Wad
        # Prevent spending gas on small rebalances
        dust = Wad(self.mcd.vat.ilk(self.ilk.name).dust) if self.ilk else Wad.from_number(20)

        dai_to_join = Wad(0)
        dai_to_exit = Wad(0)
        try:
            if self.arguments.vat_dai_target.upper() == "ALL":
                dai_to_join = token_balance
            else:
                dai_target = Wad.from_number(float(self.arguments.vat_dai_target))
                if dai_target < dust:
                    self.logger.warning(f"Dust cutoff of {dust} exceeds Dai target {dai_target}; "
                                        "please adjust configuration accordingly")
                vat_balance = Wad(self.vat.dai(self.our_address))
                if vat_balance < dai_target:
                    dai_to_join = dai_target - vat_balance
                elif vat_balance > dai_target:
                    dai_to_exit = vat_balance - dai_target
        except ValueError:
            raise ValueError("Unsupported --vat-dai-target")

        if dai_to_join >= dust:
            # Join tokens to the vat
            if token_balance >= dai_to_join:
                self.logger.info(f"Joining {str(dai_to_join)} Dai to the Vat")
                return self.join_dai(dai_to_join)
            elif token_balance > Wad(0):
                self.logger.warning(f"Insufficient balance to maintain Dai target; joining {str(token_balance)} "
                                    "Dai to the Vat")
                return self.join_dai(token_balance)
            else:
                self.logger.warning("Insufficient Dai is available to join to Vat; cannot maintain Dai target")
                return Wad(0)
        elif dai_to_exit > dust:
            # Exit dai from the vat
            self.logger.info(f"Exiting {str(dai_to_exit)} Dai from the Vat")
            assert self.dai_join.exit(self.our_address, dai_to_exit).transact(gas_price=self.gas_price)
            return dai_to_exit * -1
        self.logger.info(f"Dai token balance: {str(dai.balance_of(self.our_address))}, "
                         f"Vat balance: {self.vat.dai(self.our_address)}")

    def join_dai(self, amount: Wad):
        assert isinstance(amount, Wad)
        assert not self.is_joining_dai
        try:
            self.is_joining_dai = True
            assert self.dai_join.join(self.our_address, amount).transact(gas_price=self.gas_price)
        finally:
            self.is_joining_dai = False
        return amount

    def exit_gem(self):
        if not self.collateral:
            return

        token = Token(self.collateral.ilk.name.split('-')[0], self.collateral.gem.address, self.collateral.adapter.dec())
        vat_balance = self.vat.gem(self.ilk, self.our_address)
        if vat_balance > token.min_amount:
            self.logger.info(f"Exiting {str(vat_balance)} {self.ilk.name} from the Vat")
            assert self.gem_join.exit(self.our_address, token.unnormalize_amount(vat_balance)).transact(gas_price=self.gas_price)

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
