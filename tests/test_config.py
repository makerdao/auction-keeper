# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel
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

import asyncio
import time
import pytest

from auction_keeper.gas import DynamicGasPrice, UpdatableGasPrice
from auction_keeper.main import AuctionKeeper
from pymaker import Address, Transact, Wad
from pymaker.auctions import Flipper, Flapper, Flopper
from pymaker.dss import Cat, DaiJoin, GemJoin, Vow
from pymaker.token import DSToken
from tests.conftest import keeper_address, mcd, web3
from tests.helper import args, TransactionIgnoringTest, wait_for_other_threads


class TestTransactionMocking(TransactionIgnoringTest):
    def setup_class(self):
        """ I'm excluding initialization of a specific collateral perchance we use multiple collaterals
        to improve test speeds.  This prevents us from instantiating the keeper as a class member. """
        self.web3 = web3()
        self.mcd = mcd(self.web3)
        self.keeper_address = keeper_address(self.mcd.web3)
        self.web3.eth.defaultAccount = self.keeper_address.address
        self.collateral = self.mcd.collaterals['ETH-A']
        self.collateral.approve(self.keeper_address)
        assert self.collateral.gem.deposit(Wad.from_number(1)).transact()
        self.ilk = self.collateral.ilk

    def test_empty_tx(self):
        empty_tx = Transact(self, self.web3, None, self.keeper_address, None, None, [self.keeper_address, Wad(0)])
        empty_tx.transact()

    @pytest.mark.timeout(15)
    def test_ignore_sync_transaction(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)

        self.start_ignoring_sync_transactions()
        assert self.collateral.adapter.join(self.keeper_address, Wad.from_number(0.2)).transact()
        self.end_ignoring_sync_transactions()

        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before == balance_after

        self.check_sync_transaction_still_works()
        self.check_async_transaction_still_works()

    @pytest.mark.timeout(30)
    def test_replace_async_transaction(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)
        self.start_ignoring_transactions()
        amount1 = Wad.from_number(0.11)
        tx1 = self.collateral.adapter.join(self.keeper_address, amount1)
        AuctionKeeper._run_future(tx1.transact_async())
        self.end_ignoring_transactions()

        amount2 = Wad.from_number(0.14)
        tx2 = self.collateral.adapter.join(self.keeper_address, amount2)
        AuctionKeeper._run_future(tx2.transact_async(replace=tx1))

        # Wait for async tx threads to exit normally (should consider doing this after every async test)
        wait_for_other_threads()
        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before + amount2 == balance_after

        self.check_sync_transaction_still_works()
        self.check_async_transaction_still_works()

    @pytest.mark.timeout(30)
    def test_replace_async_transaction_delay_expensive_call_while_ignoring_tx(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)
        self.start_ignoring_transactions()
        amount1 = Wad.from_number(0.12)
        tx1 = self.collateral.adapter.join(self.keeper_address, amount1)
        AuctionKeeper._run_future(tx1.transact_async())
        time.sleep(2)
        self.end_ignoring_transactions()

        amount2 = Wad.from_number(0.15)
        tx2 = self.collateral.adapter.join(self.keeper_address, amount2)
        AuctionKeeper._run_future(tx2.transact_async(replace=tx1))

        # Wait for async tx threads to exit normally (should consider doing this after every async test)
        wait_for_other_threads()
        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before + amount2 == balance_after

        self.check_sync_transaction_still_works()
        self.check_async_transaction_still_works()

    @pytest.mark.timeout(30)
    def test_replace_async_transaction_delay_expensive_call_after_ignoring_tx(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)
        self.start_ignoring_transactions()
        amount1 = Wad.from_number(0.13)
        tx1 = self.collateral.adapter.join(self.keeper_address, amount1)
        AuctionKeeper._run_future(tx1.transact_async())
        self.end_ignoring_transactions()

        time.sleep(2)
        amount2 = Wad.from_number(0.16)
        tx2 = self.collateral.adapter.join(self.keeper_address, amount2)
        AuctionKeeper._run_future(tx2.transact_async(replace=tx1))

        # Wait for async tx threads to exit normally (should consider doing this after every async test)
        wait_for_other_threads()
        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before + amount2 == balance_after

        self.check_sync_transaction_still_works()
        self.check_async_transaction_still_works()

    def check_sync_transaction_still_works(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)
        amount = Wad.from_number(0.01)
        assert self.collateral.adapter.join(self.keeper_address, amount).transact()
        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before + amount == balance_after

    def check_async_transaction_still_works(self):
        balance_before = self.mcd.vat.gem(self.ilk, self.keeper_address)
        amount = Wad.from_number(0.01)
        AuctionKeeper._run_future(self.collateral.adapter.exit(self.keeper_address, amount).transact_async())
        wait_for_other_threads()
        balance_after = self.mcd.vat.gem(self.ilk, self.keeper_address)
        assert balance_before - amount == balance_after


class TestConfig:
    def test_flip_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk USDC-A "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flipper, Flipper)
        assert keeper.collateral.flipper == keeper.flipper
        assert keeper.collateral.ilk.name == 'USDC-A'
        assert keeper.flapper is None
        assert keeper.flopper is None
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.gem_join, GemJoin)

    def test_flip_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(RuntimeError) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flip "
                                    f"--from-block 1 "
                                    f"--model ./bogus-model.sh"), web3=web3)
        assert "ilk" in str(e)

    def test_flap_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flap "
                                         f"--from-block 1 "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flapper, Flapper)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.mkr, DSToken)
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.vow, Vow)

    def test_flap_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(SystemExit) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flap"), web3=web3)

    def test_flop_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flop "
                                         f"--from-block 1 "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flopper, Flopper)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.mkr, DSToken)
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.vow, Vow)

    def test_flop_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(RuntimeError) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flop "
                                    f"--model ./bogus-model.sh"), web3=web3)

    def create_sharded_keeper(self, web3, keeper_address: Address, shard: int):
        return AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                       f"--type flip "
                                       f"--from-block 1 "
                                       f"--ilk ETH-B "
                                       f"--shards 3 --shard-id {shard} "
                                       f"--model ./bogus-model.sh"), web3=web3)

    def test_sharding(self, web3, keeper_address: Address):
        keeper0 = self.create_sharded_keeper(web3, keeper_address, 0)
        keeper1 = self.create_sharded_keeper(web3, keeper_address, 1)
        keeper2 = self.create_sharded_keeper(web3, keeper_address, 2)

        handled0 = 0
        handled1 = 0
        handled2 = 0

        shards = 3
        auction_count = shards * 10

        for id in range(1, auction_count + 1):
            handled0 += keeper0.auction_handled_by_this_shard(id)
            handled1 += keeper1.auction_handled_by_this_shard(id)
            handled2 += keeper2.auction_handled_by_this_shard(id)

        assert handled0 == handled1 == handled2
        assert handled0 + handled1 + handled2 == auction_count

    def test_deal_list(self, web3, keeper_address: Address):
        accounts = ["0x40418beb7f24c87ab2d5ffb8404665414e91d858",
                    "0x4A8638b3788c554563Ef2444f86F943ab0Cd9761",
                    "0xdb33dfd3d61308c33c63209845dad3e6bfb2c674"]

        default_behavior = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                   f"--type flip --from-block 1 "
                                                   f"--ilk ETH-B "
                                                   f"--model ./bogus-model.sh"), web3=web3)
        assert 1 == len(default_behavior.deal_for)
        assert keeper_address == list(default_behavior.deal_for)[0]
        assert not default_behavior.deal_all

        deal_for_3_accounts = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                      f"--type flap --from-block 1 "
                                                      f"--deal-for {accounts[0]} {accounts[1]} {accounts[2]} "
                                                      f"--model ./bogus-model.sh"), web3=web3)
        assert 3 == len(deal_for_3_accounts.deal_for)
        for account in accounts:
            assert Address(account) in deal_for_3_accounts.deal_for
        assert not deal_for_3_accounts.deal_all

        disable_deal = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                               f"--type flop --from-block 1 "
                                               f"--deal-for NONE "
                                               f"--model ./bogus-model.sh"), web3=web3)
        assert 0 == len(disable_deal.deal_for)
        assert not disable_deal.deal_all

        deal_all = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                           f"--type flop --from-block 1 "
                                           f"--deal-for ALL "
                                           f"--model ./bogus-model.sh"), web3=web3)
        assert deal_all.deal_all
