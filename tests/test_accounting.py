# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019-2020 EdNoepel
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

import pytest
import threading
import time

from auction_keeper.logic import Reservoir
from auction_keeper.main import AuctionKeeper
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import keeper_address, geb, our_address, web3, wrap_eth, purchase_system_coin
from tests.helper import args

class TestSAFEEngineSystemCoin:
    def setup_method(self):
        self.web3 = web3()
        self.geb = geb(web3())
        self.keeper_address = keeper_address(web3())
        self.geb.approve_system_coin(self.keeper_address)
        self.our_address = our_address(web3())
        self.geb.approve_system_coin(self.our_address)
        self.collateral = self.geb.collaterals['ETH-B']

    def get_system_coin_token_balance(self) -> Wad:
        return self.geb.system_coin.balance_of(self.keeper_address)

    def get_system_coin_safe_engine_balance(self) -> Wad:
        return Wad(self.geb.safe_engine.coin_balance(self.keeper_address))

    def get_collateral_token_balance(self) -> Wad:
        return self.collateral.collateral.balance_of(self.keeper_address)

    def get_collateral_safe_engine_balance(self) -> Wad:
        return self.geb.safe_engine.token_collateral(self.collateral.collateral_type, self.keeper_address)

    def give_away_system_coin(self):
        assert self.geb.web3.eth.defaultAccount == self.keeper_address.address
        assert self.geb.system_coin_adapter.exit(self.keeper_address, self.get_system_coin_safe_engine_balance())
        assert self.geb.system_coin.transfer(self.our_address, self.get_system_coin_token_balance()).transact()


#@pytest.mark.skip("")
class TestSAFEEngineSystemCoinTarget(TestSAFEEngineSystemCoin):
    def create_keeper(self, system_coin: float):
        assert isinstance(system_coin, float)
        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type debt "
                                         f"--from-block 1 "
                                         f"--safe-engine-system-coin-target {system_coin} "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        keeper.startup()
        return keeper

    def create_keeper_join_all(self):
        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type debt "
                                         f"--from-block 1 "
                                         f"--safe-engine-system-coin-target all "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        keeper.startup()
        return keeper

    def test_no_change(self):
        # given balances before
        token_balance_before = self.get_system_coin_token_balance()
        safe_engine_balance_before = self.get_system_coin_safe_engine_balance()

        # when rebalancing with the current safe_engine amount
        self.create_keeper(float(safe_engine_balance_before))

        # then ensure no balances changed
        assert token_balance_before == self.get_system_coin_token_balance()
        assert safe_engine_balance_before == self.get_system_coin_safe_engine_balance()

    def test_join_enough(self, keeper_address):
        # given purchasing some system_coin
        purchase_system_coin(Wad.from_number(237), keeper_address)
        token_balance_before = self.get_system_coin_token_balance()
        assert token_balance_before == Wad.from_number(237)

        # when rebalancing with a smaller amount than we have
        self.create_keeper(153.0)

        # then ensure system_coin was joined to the safe_engine
        assert token_balance_before > self.get_system_coin_token_balance()
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(153)

    def test_join_not_enough(self):
        # given balances before
        assert self.get_system_coin_token_balance() == Wad.from_number(84)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(153)

        # when rebalancing without enough tokens to cover the difference
        self.create_keeper(500.0)

        # then ensure all available tokens were joined
        assert self.get_system_coin_token_balance() == Wad(0)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(237)

    def test_exit_some(self):
        # given balances before
        assert self.get_system_coin_token_balance() == Wad(0)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(237)

        # when rebalancing to a smaller amount than currently in the safe_engine
        self.create_keeper(200.0)

        # then ensure balances are as expected
        assert self.get_system_coin_token_balance() == Wad.from_number(37)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(200)

    def test_exit_all(self):
        # given balances before
        assert self.get_system_coin_token_balance() == Wad.from_number(37)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(200)

        # when rebalancing to 0
        self.create_keeper(0.0)

        # then ensure all system_coin has been exited
        assert self.get_system_coin_token_balance() == Wad.from_number(237)
        assert self.get_system_coin_safe_engine_balance() == Wad(0)

    def test_join_all(self):
        # given system_coin we just exited
        token_balance_before = self.get_system_coin_token_balance()
        assert token_balance_before == Wad.from_number(237)

        # when keeper is started with a token balance
        self.create_keeper_join_all()

        # then ensure all available tokens were joined
        assert self.get_system_coin_token_balance() == Wad(0)
        assert self.get_system_coin_safe_engine_balance() == Wad.from_number(237)

#@pytest.mark.skip("")  
class TestEmptySAFEEngineOnExitTarget(TestSAFEEngineSystemCoin):
    def create_keeper(self, exit_system_coin_on_shutdown: bool, exit_collateral_on_shutdown: bool):
        assert isinstance(exit_system_coin_on_shutdown, bool)
        assert isinstance(exit_collateral_on_shutdown, bool)

        safe_engine_system_coin_behavior = "" if exit_system_coin_on_shutdown else "--keep-system-coin-in-safe-engine-on-exit"
        safe_engine_collateral_behavior = "" if exit_collateral_on_shutdown else "--keep-collateral-in-safe-engine-on-exit"

        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type collateral --collateral-type {self.collateral.collateral_type.name} "
                                         f"--from-block 1 "
                                         f"--safe-engine-system-coin-target 30 "
                                         f"{safe_engine_system_coin_behavior} "
                                         f"{safe_engine_collateral_behavior} "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        self.web3 = keeper.web3
        self.geb = keeper.geb
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        assert keeper.arguments.exit_system_coin_on_shutdown == exit_system_coin_on_shutdown
        assert keeper.arguments.exit_collateral_on_shutdown == exit_collateral_on_shutdown
        keeper.startup()
        return keeper

    def test_do_not_empty(self):
        # given system_coin and collateral in the safe_engine
        keeper = self.create_keeper(False, False)
        purchase_system_coin(Wad.from_number(153), self.keeper_address)
        assert self.get_system_coin_token_balance() >= Wad.from_number(153)
        assert self.geb.system_coin_adapter.join(self.keeper_address, Wad.from_number(153)).transact(
            from_address=self.keeper_address)
        wrap_eth(self.geb, self.keeper_address, Wad.from_number(6))
        # and balances before
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when creating and shutting down the keeper
        keeper.shutdown()

        # then ensure no balances changed
        assert system_coin_token_balance_before == self.get_system_coin_token_balance()
        assert system_coin_safe_engine_balance_before == self.get_system_coin_safe_engine_balance()
        assert collateral_token_balance_before == self.get_collateral_token_balance()
        assert collateral_safe_engine_balance_before == self.get_collateral_safe_engine_balance()

    def test_empty_system_coin_only(self):
        # given balances before
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, False)
        keeper.shutdown()

        # then ensure the system_coin was emptied
        assert self.get_system_coin_token_balance() == system_coin_token_balance_before + system_coin_safe_engine_balance_before
        assert self.get_system_coin_safe_engine_balance() == Wad(0)
        # and collateral was not emptied
        assert collateral_token_balance_before == self.get_collateral_token_balance()
        assert collateral_safe_engine_balance_before == self.get_collateral_safe_engine_balance()

    def test_empty_collateral_only(self):
        # given collateral balances before
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when adding system_coin
        purchase_system_coin(Wad.from_number(79), self.keeper_address)
        assert self.geb.system_coin_adapter.join(self.keeper_address, Wad.from_number(79)).transact(
            from_address=self.keeper_address)
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        # and creating and shutting down the keeper
        keeper = self.create_keeper(False, True)
        keeper.shutdown()

        # then ensure system_coin was not emptied
        assert system_coin_token_balance_before == self.get_system_coin_token_balance()
        assert system_coin_safe_engine_balance_before == self.get_system_coin_safe_engine_balance()
        # and collateral was emptied
        assert collateral_token_balance_before == collateral_token_balance_before + collateral_safe_engine_balance_before
        assert self.get_collateral_safe_engine_balance() == Wad(0)

    def test_empty_both(self):
        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, True)
        keeper.shutdown()

        # then ensure the safe_engine is empty
        assert self.get_system_coin_safe_engine_balance() == Wad(0)
        assert self.get_collateral_safe_engine_balance() == Wad(0)

        # clean up
        self.give_away_system_coin()

@pytest.mark.skip("")  
class TestEmptySAFEEngineOnExitTargetAll(TestSAFEEngineSystemCoin):
    def create_keeper(self, exit_system_coin_on_shutdown: bool, exit_collateral_on_shutdown: bool):
        assert isinstance(exit_system_coin_on_shutdown, bool)
        assert isinstance(exit_collateral_on_shutdown, bool)

        safe_engine_system_coin_behavior = "" if exit_system_coin_on_shutdown else "--keep-system-coin-in-safe-engine-on-exit"
        safe_engine_collateral_behavior = "" if exit_collateral_on_shutdown else "--keep-collateral-in-safe-engine-on-exit"

        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type collateral --collateral-type {self.collateral.collateral_type.name} "
                                         f"--from-block 1 "
                                         f"{safe_engine_system_coin_behavior} "
                                         f"{safe_engine_collateral_behavior} "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        self.web3 = keeper.web3
        self.geb = keeper.geb
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        assert keeper.arguments.exit_system_coin_on_shutdown == exit_system_coin_on_shutdown
        assert keeper.arguments.exit_collateral_on_shutdown == exit_collateral_on_shutdown
        keeper.startup()
        return keeper

    def test_do_not_empty(self):
        # given system_coin and collateral in the safe_engine
        keeper = self.create_keeper(False, False)
        purchase_system_coin(Wad.from_number(153), self.keeper_address)
        assert self.get_system_coin_token_balance() >= Wad.from_number(153)
        assert self.geb.system_coin_adapter.join(self.keeper_address, Wad.from_number(153)).transact(
            from_address=self.keeper_address)
        wrap_eth(self.geb, self.keeper_address, Wad.from_number(6))
        # and balances before
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when creating and shutting down the keeper
        keeper.shutdown()

        # then ensure no balances changed
        assert system_coin_token_balance_before == self.get_system_coin_token_balance()
        assert system_coin_safe_engine_balance_before == self.get_system_coin_safe_engine_balance()
        assert collateral_token_balance_before == self.get_collateral_token_balance()
        assert collateral_safe_engine_balance_before == self.get_collateral_safe_engine_balance()

    def test_empty_system_coin_only(self):
        # given balances before
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, False)
        keeper.shutdown()

        # then ensure the system_coin was emptied
        assert self.get_system_coin_token_balance() == system_coin_token_balance_before + system_coin_safe_engine_balance_before
        assert self.get_system_coin_safe_engine_balance() == Wad(0)
        # and collateral was not emptied
        assert collateral_token_balance_before == self.get_collateral_token_balance()
        assert collateral_safe_engine_balance_before == self.get_collateral_safe_engine_balance()

    def test_empty_collateral_only(self):
        # given collateral balances before
        collateral_token_balance_before = self.get_collateral_token_balance()
        collateral_safe_engine_balance_before = self.get_collateral_safe_engine_balance()

        # when adding system_coin
        purchase_system_coin(Wad.from_number(79), self.keeper_address)
        assert self.geb.system_coin_adapter.join(self.keeper_address, Wad.from_number(79)).transact(
            from_address=self.keeper_address)
        system_coin_token_balance_before = self.get_system_coin_token_balance()
        system_coin_safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
        # and creating and shutting down the keeper
        keeper = self.create_keeper(False, True)
        keeper.shutdown()

        # then ensure system_coin was not emptied
        assert self.get_system_coin_token_balance() == Wad(0)
        assert system_coin_safe_engine_balance_before == self.get_system_coin_safe_engine_balance()
        # and collateral was emptied
        assert collateral_token_balance_before == collateral_token_balance_before + collateral_safe_engine_balance_before
        assert self.get_collateral_safe_engine_balance() == Wad(0)

    def test_empty_both(self):
        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, True)
        keeper.shutdown()

        # then ensure the safe_engine is empty
        assert self.get_system_coin_safe_engine_balance() == Wad(0)
        assert self.get_collateral_safe_engine_balance() == Wad(0)

        # clean up
        self.give_away_system_coin()
#@pytest.mark.skip("")  
class TestRebalance(TestSAFEEngineSystemCoin):
    def create_keeper(self, mocker, system_coin_target="all"):
        # Create a keeper
        mocker.patch("web3.net.Net.peer_count", return_value=1)
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type collateral --collateral-type ETH-C --bid-only "
                                         f"--safe-engine-system-coin-target {system_coin_target} "
                                         f"--return-collateral-interval 3 "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        self.web3 = self.keeper.web3
        self.geb = self.keeper.geb
        assert self.keeper.auctions
        # Changed the collateral to ETH-C because our testchain didn't have dust set for ETH-A or ETH-B
        self.collateral = self.keeper.collateral
        self.collateral.approve(self.keeper_address)

        self.thread = threading.Thread(target=self.keeper.main, daemon=True)
        self.thread.start()
        return self.keeper

    def shutdown_keeper(self):
        self.keeper.shutdown()  # HACK: Lifecycle doesn't invoke this as expected
        self.keeper.lifecycle.terminate("unit test completed")
        self.thread.join()

        # HACK: Lifecycle leaks threads; this needs to be fixed in pyflex
        import ctypes
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread is not threading.current_thread():
                    print(f"Attempting to kill thread {thread}")
                    sysexit = ctypes.py_object(SystemExit)  # Creates a C pointer to a Python "SystemExit" exception
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), sysexit)
                    time.sleep(1)

        # Ensure we don't leak threads, which would break wait_for_other_threads() later on
        assert threading.active_count() == 1

        assert self.get_system_coin_safe_engine_balance() == Wad(0)

    @pytest.mark.timeout(60)
    def test_balance_added_after_startup(self, mocker):
        try:
            # given collateral balances after starting keeper
            token_balance_before = self.get_system_coin_token_balance()
            self.create_keeper(mocker)
            time.sleep(6)  # wait for keeper to join everything on startup
            safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
            assert self.get_system_coin_token_balance() == Wad(0)
            assert safe_engine_balance_before == Wad(0)

            # when adding SystemCoin
            purchase_system_coin(Wad.from_number(77), self.keeper_address)
            assert self.get_system_coin_token_balance() == Wad.from_number(77)
            # and pretending there's a bid which requires SystemCoin
            reservoir = Reservoir(self.keeper.safe_engine.coin_balance(self.keeper_address))
            assert self.keeper.check_bid_cost(id=1, cost=Rad.from_number(20), reservoir=reservoir)

            # then ensure all SystemCoin is joined
            assert self.get_system_coin_token_balance() == Wad(0)
            assert self.get_system_coin_safe_engine_balance() == Wad.from_number(77)

            # when adding more SystemCoin and pretending there's a bid we cannot cover
            purchase_system_coin(Wad.from_number(23), self.keeper_address)
            assert self.get_system_coin_token_balance() == Wad.from_number(23)
            reservoir = Reservoir(self.keeper.safe_engine.coin_balance(self.keeper_address))
            assert not self.keeper.check_bid_cost(id=2, cost=Rad(Wad.from_number(120)), reservoir=reservoir)

            # then ensure the added SystemCoin was joined anyway
            assert self.get_system_coin_token_balance() == Wad(0)
            assert self.get_system_coin_safe_engine_balance() == Wad.from_number(100)

        finally:
            self.shutdown_keeper()
            self.give_away_system_coin()

    @pytest.mark.timeout(600)
    def test_fixed_system_coin_target(self, mocker):
        try:
            # given a keeper configured to maintained a fixed amount of SystemCoin
            target = Wad.from_number(100)
            purchase_system_coin(target * 2, self.keeper_address)
            assert self.get_system_coin_token_balance() == Wad.from_number(200)

            self.create_keeper(mocker, target)
            time.sleep(6)  # wait for keeper to join 100 on startup
            safe_engine_balance_before = self.get_system_coin_safe_engine_balance()
            assert safe_engine_balance_before == target

            # when spending SystemCoin
            assert self.keeper.system_coin_join.exit(self.keeper_address, Wad.from_number(22)).transact()
            assert self.get_system_coin_safe_engine_balance() == Wad.from_number(78)
            # and pretending there's a bid which requires more SystemCoin
            reservoir = Reservoir(self.keeper.safe_engine.coin_balance(self.keeper_address))
            assert self.keeper.check_bid_cost(id=3, cost=Rad.from_number(79), reservoir=reservoir)

            # then ensure SystemCoin was joined up to the target
            assert self.get_system_coin_safe_engine_balance() == target

            # when pretending there's a bid which we have plenty of SystemCoin to cover
            reservoir = Reservoir(self.keeper.safe_engine.coin_balance(self.keeper_address))
            assert self.keeper.check_bid_cost(id=4, cost=Rad(Wad.from_number(1)), reservoir=reservoir)

            # then ensure SystemCoin levels haven't changed
            assert self.get_system_coin_safe_engine_balance() == target

        finally:
            self.shutdown_keeper()

    @pytest.mark.timeout(30)
    def test_collateral_removal(self, mocker):
        try:
            # given a keeper configured to return all collateral upon rebalance
            token_balance_before = self.get_collateral_token_balance()
            safe_engine_balance_before = self.get_collateral_safe_engine_balance()
            self.create_keeper(mocker)
            time.sleep(6)  # wait for keeper to startup
            assert self.get_collateral_token_balance() == token_balance_before
            assert self.get_collateral_safe_engine_balance() == safe_engine_balance_before

            # when some ETH was wrapped and joined
            wrap_eth(self.geb, self.keeper_address, Wad.from_number(1.53))
            token_balance = self.get_collateral_token_balance()
            assert token_balance > Wad(0)
            self.collateral.adapter.join(self.keeper_address, token_balance).transact()
            assert self.get_collateral_safe_engine_balance() == safe_engine_balance_before + token_balance

            # then wait to ensure collateral was exited automatically
            time.sleep(4)
            assert self.get_collateral_safe_engine_balance() == Wad(0)
            assert self.get_collateral_token_balance() == token_balance_before + Wad.from_number(1.53)

        finally:
            self.shutdown_keeper()

        self.give_away_system_coin()

#@pytest.mark.skip("")  
class TestSwapCollateral(TestSAFEEngineSystemCoin):
    def create_keeper(self, mocker, system_coin_target="all"):
        # Create a keeper
        mocker.patch("web3.net.Net.peer_count", return_value=1)
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type collateral --collateral-type ETH-B --bid-only "
                                         f"--safe-engine-system-coin-target {system_coin_target} "
                                         f"--return-collateral-interval 3 "
                                         f"--swap-collateral "
                                         f"--max-swap-slippage 0.05 "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        self.web3 = self.keeper.web3
        self.geb = self.keeper.geb
        assert self.keeper.auctions
        # Changed the collateral to ETH-C because our testchain didn't have dust set for ETH-A or ETH-B
        self.collateral = self.keeper.collateral
        self.collateral.approve(self.keeper_address)

        self.thread = threading.Thread(target=self.keeper.main, daemon=True)
        self.thread.start()
        return self.keeper

    def shutdown_keeper(self):
        self.keeper.shutdown()  # HACK: Lifecycle doesn't invoke this as expected
        self.keeper.lifecycle.terminate("unit test completed")
        self.thread.join()

        # HACK: Lifecycle leaks threads; this needs to be fixed in pyflex
        import ctypes
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread is not threading.current_thread():
                    print(f"Attempting to kill thread {thread}")
                    sysexit = ctypes.py_object(SystemExit)  # Creates a C pointer to a Python "SystemExit" exception
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), sysexit)
                    time.sleep(1)

        # Ensure we don't leak threads, which would break wait_for_other_threads() later on
        assert threading.active_count() == 1

        assert self.get_system_coin_safe_engine_balance() == Wad(0)

    @pytest.mark.timeout(30)
    def test_swap_collateral(self, mocker):
        try:
            # Starting collateral balances
            token_balance_before = self.get_collateral_token_balance()
            safe_engine_balance_before = self.get_collateral_safe_engine_balance()

            # Start keeper
            self.create_keeper(mocker)
            time.sleep(6)  # wait for keeper to startup

            # Collateral balances are unchanged after keeper startup
            assert self.get_collateral_token_balance() == token_balance_before
            assert self.get_collateral_safe_engine_balance() == safe_engine_balance_before
            
            # Keeper's starting syscoin balance
            syscoin_balance_before = self.geb.system_coin.balance_of(self.keeper_address)

            # when some ETH was wrapped and joined
            wrap_eth(self.geb, self.keeper_address, Wad.from_number(1))
            token_balance = self.get_collateral_token_balance()
            assert token_balance > Wad(0)
            self.collateral.adapter.join(self.keeper_address, Wad.from_number(1)).transact()
            assert self.get_collateral_safe_engine_balance() == safe_engine_balance_before + Wad.from_number(1)

            # then wait to ensure collateral was exited and swapped automatically
            time.sleep(4)
            # collateral exited
            assert self.get_collateral_safe_engine_balance() == Wad(0)
            # collateral withdrawn to ETH
            assert self.get_collateral_token_balance() == token_balance - Wad.from_number(1)
            # collateral swapped for syscoin
            assert self.geb.system_coin.balance_of(self.keeper_address) > syscoin_balance_before

        finally:
            self.shutdown_keeper()

        self.give_away_system_coin()

@pytest.mark.skip("")  
class TestSwapCollateralSlippage(TestSAFEEngineSystemCoin):
    def create_keeper(self, mocker, system_coin_target="all"):
        # Create a keeper
        mocker.patch("web3.net.Net.peer_count", return_value=1)
        self.keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type collateral --collateral-type ETH-B --bid-only "
                                         f"--safe-engine-system-coin-target {system_coin_target} "
                                         f"--return-collateral-interval 3 "
                                         f"--swap-collateral "
                                         f"--max-swap-slippage 0.00001 "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        self.web3 = self.keeper.web3
        self.geb = self.keeper.geb
        assert self.keeper.auctions
        # Changed the collateral to ETH-C because our testchain didn't have dust set for ETH-A or ETH-B
        self.collateral = self.keeper.collateral
        self.collateral.approve(self.keeper_address)

        self.thread = threading.Thread(target=self.keeper.main, daemon=True)
        self.thread.start()
        return self.keeper

    def shutdown_keeper(self):
        self.keeper.shutdown()  # HACK: Lifecycle doesn't invoke this as expected
        self.keeper.lifecycle.terminate("unit test completed")
        self.thread.join()

        # HACK: Lifecycle leaks threads; this needs to be fixed in pyflex
        import ctypes
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread is not threading.current_thread():
                    print(f"Attempting to kill thread {thread}")
                    sysexit = ctypes.py_object(SystemExit)  # Creates a C pointer to a Python "SystemExit" exception
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), sysexit)
                    time.sleep(1)

        # Ensure we don't leak threads, which would break wait_for_other_threads() later on
        assert threading.active_count() == 1

        assert self.get_system_coin_safe_engine_balance() == Wad(0)

    @pytest.mark.timeout(30)
    def test_swap_collateral(self, mocker):
        try:
            # Starting collateral balances
            token_balance_before = self.get_collateral_token_balance()
            safe_engine_balance_before = self.get_collateral_safe_engine_balance()

            # Start keeper
            self.create_keeper(mocker)
            time.sleep(6)  # wait for keeper to startup

            # Collateral balances are unchanged after keeper startup
            assert self.get_collateral_token_balance() == token_balance_before
            assert self.get_collateral_safe_engine_balance() == safe_engine_balance_before
            
            # Keeper's starting syscoin balance
            syscoin_balance_before = self.geb.system_coin.balance_of(self.keeper_address)

            # when some ETH was wrapped and joined
            wrap_eth(self.geb, self.keeper_address, Wad.from_number(1.53))
            token_balance = self.get_collateral_token_balance()
            assert token_balance > Wad(0)
            self.collateral.adapter.join(self.keeper_address, token_balance).transact()

            # then wait to ensure collateral was exited but not swapped due to slippage
            time.sleep(4)
            # collateral exited
            assert self.get_collateral_safe_engine_balance() == Wad(0)
            # collateral withdrawn to ETH
            assert self.get_collateral_token_balance() == Wad(0)
            # ETH not swapped for syscoin
            assert not self.geb.system_coin.balance_of(self.keeper_address) > syscoin_balance_before

        finally:
            self.shutdown_keeper()

        self.give_away_system_coin()
