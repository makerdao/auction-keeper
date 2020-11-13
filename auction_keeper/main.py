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
from pprint import pformat

from datetime import datetime
from requests.exceptions import RequestException
from typing import Optional
from web3 import Web3

from pyflex import Address, web3_via_http
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.lifecycle import Lifecycle
from pyflex.model import Token
from pyflex.numeric import Wad, Ray, Rad
from pyflex.auctions import FixedDiscountCollateralAuctionHouse

from auction_keeper.gas import DynamicGasPrice, UpdatableGasPrice
from auction_keeper.logic import Auction, Auctions, Reservoir
from auction_keeper.model import ModelFactory, Stance
from auction_keeper.strategy import SurplusAuctionStrategy, DebtAuctionStrategy
from auction_keeper.strategy import FixedDiscountCollateralAuctionStrategy
from auction_keeper.safe_history import SAFEHistory

from pyexchange.uniswapv2 import UniswapV2


class AuctionKeeper:
    logger = logging.getLogger()
    dead_after = 10  # Assume block reorgs cannot resurrect an auction id after this many blocks

    def __init__(self, args: list, **kwargs):
        parser = argparse.ArgumentParser(prog='auction-keeper')

        parser.add_argument("--rpc-uri", type=str, default="http://localhost:8545",
                            help="JSON-RPC endpoint URI with port (default: `http://localhost:8545')")
        parser.add_argument("--rpc-timeout", type=int, default=10,
                            help="JSON-RPC timeout (in seconds, default: 10)")
        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum account from which to send transactions")
        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=aaa.json,pass_file=aaa.pass')")
        parser.add_argument('--type', type=str, choices=['collateral', 'surplus', 'debt'], default='collateral',
                            help="Auction type in which to participate")
        parser.add_argument('--collateral-type', type=str, default='ETH-A',
                            help="Name of the collateral type for a collateral keeper (e.g. 'ETH-B', 'ZRX-A'); ")
        parser.add_argument('--bid-only', dest='create_auctions', action='store_false',
                            help="Do not take opportunities to create new auctions")
        parser.add_argument('--start-auctions-only', dest='bid_on_auctions', action='store_false',
                            help="Do not bid on auctions")
        parser.add_argument('--settle-auctions-for', type=str, nargs="+",
                            help="List of addresses for which auctions will be settled")
        parser.add_argument('--min-auction', type=int, default=0,
                            help="Lowest auction id to consider")
        parser.add_argument('--max-auctions', type=int, default=1000,
                            help="Maximum number of auctions to simultaneously interact with, "
                                 "used to manage OS and hardware limitations")
        parser.add_argument('--min-collateral-lot', type=float, default=0,
                            help="Minimum lot size to create or bid upon a collateral auction")
        parser.add_argument('--bid-check-interval', type=float, default=4.0,
                            help="Period of timer [in seconds] used to check bidding models for changes")
        parser.add_argument('--bid-delay', type=float, default=0.0,
                            help="Seconds to wait between bids, used to manage OS and hardware limitations")
        parser.add_argument('--block-check-interval', type=float, default=1.0,
                            help="Period of timer [in seconds] used to check for new blocks. If using Infura free-tier, you must "
                            "increase this value")
        parser.add_argument('--shard-id', type=int, default=0,
                            help="When sharding auctions across multiple keepers, this identifies the shard")
        parser.add_argument('--shards', type=int, default=1,
                            help="Number of shards; should be one greater than your highest --shard-id")
        parser.add_argument("--graph-endpoints", type=str,
                            help="Comma-delimited list of graph endpoints. When specified, safe history will be initialized "
                                 "from a Graph node, reducing load on the Ethereum node for collateral auctions. "
                                 "If multiple nodes are passed, they will be tried in order")
        parser.add_argument('--from-block', type=int, default=11120952,
                            help="Starting block from which to find vaults to liquidation or debt to queue "
                                 "(set to block where GEB was deployed)")
        parser.add_argument('--safe-engine-system-coin-target', type=str,
                            help="Amount of system coin to keep in the SAFEEngine contract or 'ALL' to join entire token balance")
        parser.add_argument('--keep-system-coin-in-safe-engine-on-exit', dest='exit_system_coin_on_shutdown', action='store_false',
                            help="Retain system coin in the SAFE Engine on exit, saving gas when restarting the keeper")
        parser.add_argument('--keep-collateral-in-safe-engine-on-exit', dest='exit_collateral_on_shutdown', action='store_false',
                            help="Retain collateral in the SAFE Engine on exit")
        parser.add_argument('--return-collateral-interval', type=int, default=300,
                            help="Period of timer [in seconds] used to check and exit won collateral")
        parser.add_argument('--swap-collateral', dest='swap_collateral', action='store_true',
                            help="After exiting won collateral, swap it on Uniswap for system coin")
        parser.add_argument('--max-swap-slippage', type=float, default=0.01,
                            help="Maximum amount of slippage allowed when swapping collateral")
        parser.add_argument("--model", type=str, nargs='+',
                            help="Commandline to use in order to start the bidding model")

        gas_group = parser.add_mutually_exclusive_group()
        gas_group.add_argument("--ethgasstation-api-key", type=str, default=None, help="ethgasstation API key")
        gas_group.add_argument('--etherchain-gas-price', dest='etherchain_gas', action='store_true',
                               help="Use etherchain.org gas price")
        gas_group.add_argument('--poanetwork-gas-price', dest='poanetwork_gas', action='store_true',
                               help="Use POANetwork gas price")
        gas_group.add_argument('--etherscan-gas-price', dest='etherscan_gas', action='store_true',
                               help="Use Etherscan gas price")
        gas_group.add_argument('--gasnow-gas-price', dest='gasnow_gas', action='store_true',
                               help="Use Gasnow gas price")
        gas_group.add_argument('--fixed-gas-price', type=float, default=None,
                               help="Uses a fixed value (in Gwei) instead of an external API to determine initial gas")

        parser.add_argument("--etherscan-key", type=str, default=None,
                            help="Optional Etherscan API key. If not specified, client is rate-limited(currently 1request/5sec")
        parser.add_argument("--gasnow-app-name", type=str, default=None,
                            help="Optional, but recommended Gasnow app name, which should be unique to your client. If not specified, "
                            "client is most-likely rate-limited")
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
        self.graph_endpoints = self.arguments.graph_endpoints.split(',') if self.arguments.graph_endpoints else None
        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))

        # Configure connection to the chain
        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else web3_via_http(
            endpoint_uri=self.arguments.rpc_uri, timeout=self.arguments.rpc_timeout, http_pool_size=100)
        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        # Check configuration for retrieving safes/liquidations
        if self.arguments.type == 'collateral' and self.arguments.create_auctions \
                and self.arguments.from_block is None and self.graph_endpoints is None:
            raise RuntimeError("Either --from-block or --graph-endpoints must be specified to kick off "
                               "collateral auctions")
        if self.arguments.type == 'collateral' and not self.arguments.collateral_type:
            raise RuntimeError("--collateral-type must be supplied when configuring a collateral keeper")
        if self.arguments.type == 'debt' and self.arguments.create_auctions \
                and self.arguments.from_block is None:
            raise RuntimeError("--from-block must be specified to start debt auctions")

        # Configure core and token contracts
        self.geb = GfDeployment.from_node(web3=self.web3)
        self.safe_engine = self.geb.safe_engine
        self.liquidation_engine = self.geb.liquidation_engine
        self.accounting_engine = self.geb.accounting_engine
        self.prot = self.geb.prot
        self.system_coin_join = self.geb.system_coin_adapter
        if self.arguments.type == 'collateral':
            self.collateral = self.geb.collaterals[self.arguments.collateral_type]
            self.collateral_type = self.collateral.collateral_type
            self.collateral_join = self.collateral.adapter
        else:
            self.collateral = None
            self.collateral_type = None
            self.collateral_join = None

        if self.arguments.swap_collateral:

            self.token_syscoin = Token("Syscoin", Address(self.geb.system_coin.address), 18)
            self.token_weth = Token("WETH", self.collateral.collateral.address, 18)
            self.weth_syscoin_path = [self.token_weth.address.address, self.geb.system_coin.address.address]

            self.syscoin_eth_uniswap = UniswapV2(self.web3, self.token_syscoin, self.token_weth, self.our_address,
                                                 self.geb.uniswap_router, self.geb.uniswap_factory)


        # Configure auction contracts
        self.collateral_auction_house = self.collateral.collateral_auction_house if self.arguments.type == 'collateral' else None
        self.surplus_auction_house = self.geb.surplus_auction_house if self.arguments.type == 'surplus' else None
        self.debt_auction_house = self.geb.debt_auction_house if self.arguments.type == 'debt' else None
        self.safe_history = None
        if self.collateral_auction_house:
            self.min_collateral_lot = Wad.from_number(self.arguments.min_collateral_lot)
            self.strategy = FixedDiscountCollateralAuctionStrategy(self.collateral_auction_house,
                                                                   self.min_collateral_lot,
                                                                   self.geb, self.our_address)

            if self.arguments.create_auctions:
                self.safe_history = SAFEHistory(self.web3, self.geb, self.collateral_type, self.arguments.from_block,
                                                self.graph_endpoints)
        elif self.surplus_auction_house:
            self.strategy = SurplusAuctionStrategy(self.surplus_auction_house, self.prot.address)
        elif self.debt_auction_house:
            self.strategy = DebtAuctionStrategy(self.debt_auction_house)
        else:
            raise RuntimeError("Please specify auction type")

        # Create the collection used to manage auctions relevant to this keeper
        if self.arguments.model:
            model_command = ' '.join(self.arguments.model)
        else:
            if self.arguments.bid_on_auctions and not isinstance(self.collateral_auction_house, FixedDiscountCollateralAuctionHouse):
                raise RuntimeError("--model must be specified to bid on auctions")
            else:
                model_command = ":"
        self.auctions = Auctions(collateral_auction_house=self.collateral_auction_house.address if self.collateral_auction_house else None,
                                 surplus_auction_house=self.surplus_auction_house.address if self.surplus_auction_house else None,
                                 debt_auction_house=self.debt_auction_house.address if self.debt_auction_house else None,
                                 model_factory=ModelFactory(model_command))
        self.auctions_lock = threading.Lock()
        # Since we don't want periodically-polled bidding threads to back up, use a flag instead of a lock.
        self.is_joining_system_coin = False
        self.dead_since = {}
        self.lifecycle = None


        # Create gas strategy used for non-bids and bids which do not supply gas price
        self.gas_price = DynamicGasPrice(self.arguments, self.web3)

        # Configure account(s) for which we'll settle auctions
        self.settle_all = False
        self.settle_auctions_for = set()
        if self.arguments.settle_auctions_for is None:
            self.settle_auctions_for.add(self.our_address)
        elif len(self.arguments.settle_auctions_for) == 1 and self.arguments.settle_auctions_for[0].upper() in ["ALL", "NONE"]:
            if self.arguments.settle_auctions_for[0].upper() == "ALL":
                self.settle_all = True
            # else no auctions will be settled
        elif len(self.arguments.settle_auctions_for) > 0:
            for account in self.arguments.settle_auctions_for:
                self.settle_auctions_for.add(Address(account))

        # reduce logspew
        logging.getLogger('urllib3').setLevel(logging.INFO)
        logging.getLogger("web3").setLevel(logging.INFO)
        logging.getLogger("asyncio").setLevel(logging.INFO)
        logging.getLogger("requests").setLevel(logging.INFO)

    def __repr__(self):
        return f"AuctionKeeper({pformat(vars(self))})"

    def main(self):
        def seq_func(check_func: callable):
            assert callable(check_func)

            # Kick off new auctions
            if self.arguments.create_auctions:
                try:
                    check_func()
                except (RequestException, ConnectionError, ValueError, AttributeError):
                    logging.exception("Error checking for opportunities to start an auction")

            # Bid on and settle existing auctions
            try:
                self.check_all_auctions()
            except (RequestException, ConnectionError, ValueError, AttributeError):
                logging.exception("Error checking auction states")

        with Lifecycle(self.web3, self.arguments.block_check_interval) as lifecycle:
            self.lifecycle = lifecycle
            lifecycle.on_startup(self.startup)
            lifecycle.on_shutdown(self.shutdown)
            if self.collateral_auction_house and self.liquidation_engine:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_safes))
            elif self.surplus_auction_house and self.accounting_engine:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_surplus))
            elif self.debt_auction_house and self.accounting_engine:
                lifecycle.on_block(functools.partial(seq_func, check_func=self.check_debt))
            else:  # unusual corner case
                lifecycle.on_block(self.check_all_auctions)

            if self.arguments.bid_on_auctions:
                lifecycle.every(self.arguments.bid_check_interval, self.check_for_bids)
            if self.arguments.return_collateral_interval:
                lifecycle.every(self.arguments.return_collateral_interval, functools.partial(self.exit_collateral, swap=self.arguments.swap_collateral))

    def auction_notice(self) -> str:
        if self.arguments.type == 'collateral':
            return "--> Check all safes and start new auctions if any" + \
                   " critical safes need to be liquidated"
        else:
            return "--> Check thresholds in Accounting Engine Contract and start new" + \
                  f" {self.arguments.type} auctions once reached"

    def startup(self):
        self.approve()
        self.rebalance_system_coin()
        if self.surplus_auction_house:
            self.logger.info(f"Prot balance is {self.prot.balance_of(self.our_address)}")

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

        if self.settle_all:
            notice_string.append("--> Check all auctions and settle for any address")
        elif len(self.settle_auctions_for) == 1:
            notice_string.append(f"--> Check all auctions and settle for {list(self.settle_auctions_for)[0].address}")
        elif len(self.settle_auctions_for) > 0:
            notice_string.append(f"--> Check all auctions and settle auctions for {[a.address for a in self.settle_auctions_for]} addresses")
        else:
            logging.info("Keeper will not settle auctions")

        if notice_string:
            logging.info("Keeper will perform the following operation(s) in parallel:")
            [logging.info(line) for line in notice_string]

            if self.collateral_auction_house and self.collateral_type and self.collateral_type.name == "ETH-A":
                logging.info("*** When Keeper is settling/bidding, the initial evaluation of auctions will likely take > 45 minutes without setting a lower boundary via '--min-auction' ***")
                logging.info("*** When Keeper is starting auctions, initializing safe history may take > 30 minutes without using Graph via `--graph-endpoints` ***")
        else:
            logging.info("Keeper is currently inactive. Consider re-running the startup script with --bid-only or --kick-only")

        logging.info(f"Keeper will use {self.gas_price} for transactions and bids unless model instructs otherwise")

    def approve(self):
        if self.arguments.swap_collateral:
            self.syscoin_eth_uniswap.approve(self.token_syscoin)
            self.syscoin_eth_uniswap.approve(self.token_weth)

        self.strategy.approve(gas_price=self.gas_price)
        time.sleep(1)
        if self.system_coin_join:
            if self.geb.system_coin.allowance_of(self.our_address, self.system_coin_join.address) > Wad.from_number(2**50):
                return
            else:
                self.geb.approve_system_coin(usr=self.our_address, gas_price=self.gas_price)
        time.sleep(1)
        if self.collateral:
            self.collateral.approve(self.our_address, gas_price=self.gas_price)

    def shutdown(self):
        with self.auctions_lock:
            del self.auctions
        if self.arguments.exit_system_coin_on_shutdown:
            self.exit_system_coin_on_shutdown()
        if self.arguments.exit_collateral_on_shutdown:
            self.exit_collateral(swap=False)# Don't swap collateral to syscoin when shutting down

    def is_shutting_down(self) -> bool:
        return self.lifecycle and self.lifecycle.terminated_externally

    def exit_system_coin_on_shutdown(self):
        # Unlike rebalance_system_coin(), this doesn't join, and intentionally doesn't check debt_floor
        safe_engine_balance = Wad(self.safe_engine.coin_balance(self.our_address))
        if safe_engine_balance > Wad(0):
            self.logger.info(f"Exiting {str(safe_engine_balance)} system coin from the SAFE Engine before shutdown")
            assert self.system_coin_join.exit(self.our_address, safe_engine_balance).transact(gas_price=self.gas_price)


    def auction_handled_by_this_shard(self, id: int) -> bool:
        assert isinstance(id, int)
        if id % self.arguments.shards == self.arguments.shard_id:
            return True
        else:
            logging.debug(f"Auction {id} is not handled by shard {self.arguments.shard_id}")
            return False

    def check_safes(self):
        started = datetime.now()
        collateral_type = self.safe_engine.collateral_type(self.collateral_type.name)
        rate = collateral_type.accumulated_rate

        available_system_coin = self.geb.system_coin.balance_of(self.our_address) + Wad(self.safe_engine.coin_balance(self.our_address))

        # Look for critical safes and liquidate them
        safes = self.safe_history.get_safes()
        logging.debug(f"Evaluating {len(safes)} {self.collateral_type} safes to be liquidated if any are critical")

        for safe in safes.values():
            is_critical = safe.locked_collateral * collateral_type.liquidation_price < safe.generated_debt * rate
            if is_critical:
                if self.arguments.bid_on_auctions and available_system_coin == Wad(0):
                    self.logger.warning(f"Skipping opportunity to liquidation safe {safe.address} "
                                        "because there is no system coin to bid")
                    break

                if safe.locked_collateral < self.min_collateral_lot:
                    self.logger.info(f"Ignoring safe {safe.address.address} with locked_collateral={safe.locked_collateral} < "
                                     f"min_lot={self.min_collateral_lot}")
                    continue

                self._run_future(self.liquidation_engine.liquidate_safe(collateral_type, safe).transact_async(gas_price=self.gas_price))

        self.logger.info(f"Checked {len(safes)} safes in {(datetime.now()-started).seconds} seconds")
        # LiquidationEngine.liquidate implicitly starts the collateral auction; no further action needed.

    def check_surplus(self):
        # Check if Accounting Engine has a surplus of system coin compared to bad debt
        total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)
        total_debt = self.safe_engine.debt_balance(self.accounting_engine.address)

        # Check if Accounting Engine has system coin in excess
        if total_surplus > total_debt:
            surplus_auction_amount_to_sell = self.accounting_engine.surplus_auction_amount_to_sell()
            surplus_buffer = self.accounting_engine.surplus_buffer()

            # Check if Accounting Engine has enough system coin surplus to start an auction and that we have enough prot balance
            if (total_surplus - total_debt) >= (surplus_auction_amount_to_sell + surplus_buffer):

                if self.arguments.bid_on_auctions and self.prot.balance_of(self.our_address) == Wad(0):
                    self.logger.warning("Skipping opportunity to settle debt/surplus because there is no prot to bid")
                    return

                unqueued_unauctioned_debt = self.accounting_engine.unqueued_unauctioned_debt()
                # Heal the system to bring Woe to 0
                if unqueued_unauctioned_debt > Rad(0):
                    self.accounting_engine.settle_debt(unqueued_unauctioned_debt).transact(gas_price=self.gas_price)
                self.accounting_engine.auction_surplus().transact(gas_price=self.gas_price)

    def reconcile_debt(self, total_surplus: Rad, total_on_auction_debt: Rad, unqueued_unauctioned_debt: Rad):
        assert isinstance(total_surplus, Rad)
        assert isinstance(total_on_auction_debt, Rad)
        assert isinstance(unqueued_unauctioned_debt, Rad)

        if total_on_auction_debt > Rad(0):
            if total_surplus > total_on_auction_debt:
                self.accounting_engine.cancel_auctioned_debt_with_surplus(total_on_auction_debt).transact(gas_price=self.gas_price)
            else:
                self.accounting_engine.cancel_auctioned_debt_with_surplus(total_surplus).transact(gas_price=self.gas_price)
                return
        if unqueued_unauctioned_debt > Rad(0):
            total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)
            if total_surplus > unqueued_unauctioned_debt:
                self.accounting_engine.settle_debt(unqueued_unauctioned_debt).transact(gas_price=self.gas_price)
            else:
                self.accounting_engine.settle_debt(total_surplus).transact(gas_price=self.gas_price)

    def check_debt(self):
        # Check if Accounting Engine has a surplus of bad debt compared to system coin
        total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)
        total_debt = self.safe_engine.debt_balance(self.accounting_engine.address)

        # Check if Accounting Engine has bad debt in excess
        excess_debt = total_surplus < total_debt
        if not excess_debt:
            return

        unqueued_unauctioned_debt = self.accounting_engine.unqueued_unauctioned_debt()
        debt_queue = self.accounting_engine.debt_queue()
        debt_auction_bid_size = self.accounting_engine.debt_auction_bid_size()
        pop_debt_delay = self.accounting_engine.pop_debt_delay()

        # Check if Accounting Engine has enough bad debt to start an auction and that we have enough system_coin balance
        if unqueued_unauctioned_debt + debt_queue >= debt_auction_bid_size:
            # We need to bring Joy to 0 and Woe to at least debt_auction_bid_size

            available_system_coin = self.geb.system_coin.balance_of(self.our_address) + Wad(self.safe_engine.coin_balance(self.our_address))
            if self.arguments.bid_on_auctions and available_system_coin == Wad(0):
                self.logger.warning("Skipping opportunity to kiss/flog/heal/debt because there is no system coin to bid")
                return

            # first use kiss() as it settled bad debt already in auctions and doesn't decrease unqueued_unauctioned_debt
            total_on_auction_debt = self.accounting_engine.total_on_auction_debt()
            if total_surplus > Rad(0):
                self.reconcile_debt(total_surplus, total_on_auction_debt, unqueued_unauctioned_debt)

            # Convert enough sin in unqueued_unauctioned_debt to have unqueued_unauctioned_debt >= debt_auction_bid_size + total_surplus
            if unqueued_unauctioned_debt < (debt_auction_bid_size + total_surplus) and self.liquidation_engine is not None:
                past_blocks = self.web3.eth.blockNumber - self.arguments.from_block
                for liquidation_event in self.liquidation_engine.past_liquidations(past_blocks):  # TODO: cache ?
                    block_time = liquidation_event.block_time(self.web3)
                    now = self.web3.eth.getBlock('latest')['timestamp']
                    debt_queue = self.accounting_engine.debt_queue_of(block_time)
                    # If the liquidation hasn't already been popped from queue and has aged past the `pop_debt_delay`
                    if debt_queue > Rad(0) and block_time + pop_debt_delay <= now:
                        self.accounting_engine.pop_debt_from_queue(block_time).transact(gas_price=self.gas_price)

                        # pop debt from queue until unqueued_unauctioned_debt is above debt_auction_bid_size + total_surplus
                        total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)
                        if self.accounting_engine.unqueued_unauctioned_debt() - total_surplus >= debt_auction_bid_size:
                            break

            # Reduce on-auction debt and reconcile remaining total_surplus
            total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)
            if total_surplus > Rad(0):
                total_on_auction_debt = self.accounting_engine.total_on_auction_debt()
                unqueued_unauctioned_debt = self.accounting_engine.unqueued_unauctioned_debt()
                self.reconcile_debt(total_surplus, total_on_auction_debt, unqueued_unauctioned_debt)
                total_surplus = self.safe_engine.coin_balance(self.accounting_engine.address)

            unqueued_unauctioned_debt = self.accounting_engine.unqueued_unauctioned_debt()
            if debt_auction_bid_size <= unqueued_unauctioned_debt and total_surplus == Rad(0):
                self.accounting_engine.auction_debt().transact(gas_price=self.gas_price)

    def check_all_auctions(self):
        started = datetime.now()
        ignored_auctions = []

        for id in range(self.arguments.min_auction, self.strategy.auctions_started() + 1):
            if not self.auction_handled_by_this_shard(id):
                continue
            with self.auctions_lock:
                # If we're exiting, release the lock around checking auctions
                if self.is_shutting_down():
                    return

                # Check whether auction needs to be handled; settle the auction if appropriate
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

        self.logger.info(f"Checked auctions {self.arguments.min_auction} to {self.strategy.auctions_started()} in " 
                         f"{(datetime.now() - started).seconds} seconds")

    def check_for_bids(self):
        # Initialize the reservoir with system coin/prot balance for this round of bid submissions.
        # This isn't a perfect solution as it omits the cost of bids submitted from the last round.
        # Recreating the reservoir preserves the stateless design of this keeper.
        if self.collateral_auction_house or self.debt_auction_house:
            reservoir = Reservoir(self.safe_engine.coin_balance(self.our_address))
        elif self.surplus_auction_house:
            reservoir = Reservoir(Rad(self.prot.balance_of(self.our_address)))
        else:
            raise RuntimeError("Unsupported auction type")
        
        with self.auctions_lock:
            for id, auction in self.auctions.auctions.items():
                # If we're exiting, release the lock around checking price models
                if self.is_shutting_down():
                    return

                if not self.auction_handled_by_this_shard(id):
                    continue
                if isinstance(self.collateral_auction_house, FixedDiscountCollateralAuctionHouse):
                    self.handle_fixed_discount_bid(id=id, auction=auction)
                else:
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
        logging.debug(f"Input for auction {id}: {input}")
        auction_deleted = (input.auction_deadline == 0)
        logging.debug(f"Auction {id} deleted: {auction_deleted}")
        if isinstance(self.collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            auction_finished = False
        else:
            auction_finished = (input.bid_expiry < input.block_time and input.bid_expiry != 0) or (input.auction_deadline < input.block_time)

        if auction_deleted:
            # Try to remove the auction so the model terminates and we stop tracking it.
            # If auction has already been removed, nothing happens.
            self.auctions.remove_auction(id)
            self.dead_since[id] = current_block
            logging.debug(f"Stopped tracking auction {id}")
            return False

        # Check if the auction is finished.  If so configured, `restart_auction` or `settle_auction` the auction synchronously.
        elif auction_finished:
            if input.bid_expiry == 0:
                if self.arguments.create_auctions:
                    logging.info(f"Auction {id} ended without bids; resurrecting auction")
                    self.strategy.restart_auction(id).transact(gas_price=self.gas_price)
                    return True
            elif self.settle_all or input.high_bidder in self.settle_auctions_for:
                self.strategy.settle_auction(id).transact(gas_price=self.gas_price)

                # Upon winning a collateral or debt auction, we may need to replenish system coin to the SAFE Engine.
                # Upon winning a surplus auction, we may want to withdraw won system coin from the SAFE Engine.
                self.rebalance_system_coin()
            else:
                logging.debug(f"Not settling {id} with high_bidder={input.high_bidder}")

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

        logging.debug(f"Feeding auction {id} model input {input}")
        # Feed the model with current state
        auction.feed_model(input)

    def handle_fixed_discount_bid(self, id: int, auction: Auction):
        assert isinstance(id, int)
        assert isinstance(auction, Auction)

        output = auction.model_output()
        if output is None:
            return

        bid_price, bid_transact, cost = self.strategy.bid(id)

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
                self.logger.info(f"Sending new bid @{bid_price} for auction {id}")
                auction.price = bid_price
                auction.gas_price = new_gas_strategy if new_gas_strategy else auction.gas_price
                auction.register_transaction(bid_transact)

                # ...submit a new transaction and wait the delay period (if so configured)
                self._run_future(bid_transact.transact_async(gas_price=auction.gas_price))
                if self.arguments.bid_delay:
                    logging.debug(f"Waiting {self.arguments.bid_delay}s")
                    time.sleep(self.arguments.bid_delay)

            # if model has been providing a gas price, and that changed...
            elif fixed_gas_price_changed:
                assert isinstance(auction.gas_price, UpdatableGasPrice)
                self.logger.info(f"Overriding pending bid with new gas_price ({output.gas_price}) for auction {id}")
                auction.gas_price.update_gas_price(output.gas_price)

            # if transaction in progress, but gas strategy changed...
            elif new_gas_strategy:
                self.logger.info(f"Changing gas strategy for pending bid @{output.price} for auction {id}")
                auction.price = bid_price
                auction.gas_price = new_gas_strategy
                auction.register_transaction(bid_transact)

                # ...ask pyflex to replace the transaction
                self._run_future(bid_transact.transact_async(replace=transaction_in_progress,
                                                             gas_price=auction.gas_price))

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

                # ...ask pyflex to replace the transaction
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

                # ...ask pyflex to replace the transaction
                self._run_future(bid_transact.transact_async(replace=transaction_in_progress,
                                                             gas_price=auction.gas_price))

    def check_bid_cost(self, id: int, cost: Rad, reservoir: Reservoir, already_rebalanced=False) -> bool:
        assert isinstance(id, int)
        assert isinstance(cost, Rad)

        # If this is an auction where we bid with system coin...
        if self.collateral_auction_house or self.debt_auction_house:
            if not reservoir.check_bid_cost(id, cost):
                if not already_rebalanced:
                    # Try to synchronously join system coin the SAFE Engine
                    if self.is_joining_system_coin:
                        self.logger.info(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                          "waiting for system coin to rebalance")
                        return False
                    else:
                        rebalanced = self.rebalance_system_coin()
                        if rebalanced and rebalanced > Wad(0):
                            reservoir.refill(Rad(rebalanced))
                            return self.check_bid_cost(id, cost, reservoir, already_rebalanced=True)

                self.logger.info(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                  "bid will not be submitted")
                return False
        # If this is an auction where we bid with prot...
        elif self.surplus_auction_house:
            prot_balance = self.prot.balance_of(self.our_address)
            if cost > Rad(prot_balance):
                self.logger.debug(f"Bid cost {str(cost)} exceeds reservoir level of {reservoir.level}; "
                                  "bid will not be submitted")
                return False
        return True

    def rebalance_system_coin(self) -> Optional[Wad]:
        # Returns amount joined (positive) or exited (negative) as a result of rebalancing towards safe_engine_system_coin_target

        if self.arguments.safe_engine_system_coin_target is None:
            return None

        logging.info(f"Checking if internal system coin balance needs to be rebalanced")
        system_coin = self.system_coin_join.system_coin()
        token_balance = system_coin.balance_of(self.our_address)  # Wad
        # Prevent spending gas on small rebalances
        debt_floor = Wad(self.geb.safe_engine.collateral_type(self.collateral_type.name).debt_floor) if self.collateral_type else Wad.from_number(20)

        system_coin_to_join = Wad(0)
        system_coin_to_exit = Wad(0)
        try:
            if self.arguments.safe_engine_system_coin_target.upper() == "ALL":
                system_coin_to_join = token_balance
            else:
                system_coin_target = Wad.from_number(float(self.arguments.safe_engine_system_coin_target))
                if system_coin_target < debt_floor:
                    self.logger.warning(f"Dust cutoff of {debt_floor} exceeds system coin target {system_coin_target}; "
                                        "please adjust configuration accordingly")
                safe_engine_balance = Wad(self.safe_engine.coin_balance(self.our_address))
                if safe_engine_balance < system_coin_target:
                    system_coin_to_join = system_coin_target - safe_engine_balance
                elif safe_engine_balance > system_coin_target:
                    system_coin_to_exit = safe_engine_balance - system_coin_target
        except ValueError:
            raise ValueError("Unsupported --safe-engine-system-coin-target")

        if system_coin_to_join >= debt_floor:
            # Join tokens to the safe_engine
            if token_balance >= system_coin_to_join:
                self.logger.info(f"Joining {str(system_coin_to_join)} system coin to the SAFE Engine")
                return self.join_system_coin(system_coin_to_join)
            elif token_balance > Wad(0):
                self.logger.warning(f"Insufficient balance to maintain system coin target; joining {str(token_balance)} "
                                    "system coin to the SAFE Engine")
                return self.join_system_coin(token_balance)
            else:
                self.logger.warning("Insufficient system coin is available to join to SAFE Engine; cannot maintain system coin target")
                return Wad(0)
        elif system_coin_to_exit > debt_floor:
            # Exit system_coin from the safe_engine
            self.logger.info(f"Exiting {str(system_coin_to_exit)} system coin from the SAFE Engine")
            assert self.system_coin_join.exit(self.our_address, system_coin_to_exit).transact(gas_price=self.gas_price)
            return system_coin_to_exit * -1
        self.logger.info(f"system coin token balance: {str(system_coin.balance_of(self.our_address))}, "
                         f"SAFE Engine balance: {self.safe_engine.coin_balance(self.our_address)}")

    def join_system_coin(self, amount: Wad):
        assert isinstance(amount, Wad)
        assert not self.is_joining_system_coin
        try:
            self.is_joining_system_coin = True
            assert self.system_coin_join.join(self.our_address, amount).transact(gas_price=self.gas_price)
        finally:
            self.is_joining_system_coin = False
        return amount

    def exit_collateral(self, swap: bool):
        if not self.collateral:
            return

        token = Token(self.collateral.collateral_type.name.split('-')[0], self.collateral.collateral.address, self.collateral.adapter.decimals())
        safe_engine_balance = self.safe_engine.token_collateral(self.collateral_type, self.our_address)
        if safe_engine_balance <= token.min_amount:
            return

        collateral_amount = token.unnormalize_amount(safe_engine_balance)
        self.logger.info(f"Exiting {str(safe_engine_balance)} {self.collateral_type.name} from the SAFE Engine")
        assert self.collateral_join.exit(self.our_address, collateral_amount).transact(gas_price=self.gas_price)

        if not swap:
            return

        self.logger.info(f"Swapping {str(safe_engine_balance)} {self.collateral_type.name} for system coin on Uniswap")
        exchange_rate = self.syscoin_eth_uniswap.get_exchange_rate()
        min_amount_out = collateral_amount / exchange_rate * (Wad.from_number(1) - Wad.from_number(self.arguments.max_swap_slippage))
        assert self.collateral.collateral.withdraw(collateral_amount).transact()
        if not self.syscoin_eth_uniswap.swap_exact_eth_for_tokens(collateral_amount, min_amount_out, self.weth_syscoin_path).transact():
            self.logger.warn(f"Unable to swap collateral for syscoin with less than {self.arguments.max_swap_slippage} slippage")

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
