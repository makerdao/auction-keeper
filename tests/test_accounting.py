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

import pytest

from auction_keeper.main import AuctionKeeper
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import keeper_address, mcd, our_address, reserve_dai, web3, wrap_eth
from tests.helper import args


class TestVatDai:
    def setup_method(self):
        self.web3 = web3()
        self.mcd = mcd(web3())
        self.keeper_address = keeper_address(web3())
        self.mcd.approve_dai(self.keeper_address)
        self.our_address = our_address(web3())
        self.mcd.approve_dai(self.our_address)
        self.collateral = self.mcd.collaterals['ETH-B']

    def get_dai_token_balance(self) -> Wad:
        return self.mcd.dai.balance_of(self.keeper_address)

    def get_dai_vat_balance(self) -> Wad:
        return Wad(self.mcd.vat.dai(self.keeper_address))

    def get_gem_token_balance(self) -> Wad:
        return self.collateral.gem.balance_of(self.keeper_address)

    def get_gem_vat_balance(self) -> Wad:
        return self.mcd.vat.gem(self.collateral.ilk, self.keeper_address)

    def purchase_dai(self, amount: Wad):
        assert isinstance(amount, Wad)
        seller = self.our_address
        reserve_dai(self.mcd, self.mcd.collaterals['ETH-C'], seller, amount)
        assert self.mcd.dai_adapter.exit(seller, amount).transact(from_address=seller)
        assert self.mcd.dai.transfer_from(seller, self.keeper_address, amount).transact(from_address=seller)


class TestVatDaiTarget(TestVatDai):
    def create_keeper(self, dai: float):
        assert isinstance(dai, float)
        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type flop "
                                         f"--network testnet "
                                         f"--vat-dai-target {dai} "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        assert keeper.vat_dai_target == Wad.from_number(dai)
        keeper.startup()
        return keeper

    def test_no_change(self):
        # given balances before
        token_balance_before = self.get_dai_token_balance()
        vat_balance_before = self.get_dai_vat_balance()

        # when rebalancing with the current vat amount
        self.create_keeper(float(vat_balance_before))

        # then ensure no balances changed
        assert token_balance_before == self.get_dai_token_balance()
        assert vat_balance_before == self.get_dai_vat_balance()

    def test_join_enough(self):
        # given purchasing some dai
        self.purchase_dai(Wad.from_number(237))
        token_balance_before = self.get_dai_token_balance()
        assert token_balance_before == Wad.from_number(237)
        vat_balance_before = self.get_dai_vat_balance()

        # when rebalancing with a smaller amount than we have
        self.create_keeper(153.0)

        # then ensure dai was joined to the vat
        assert token_balance_before > self.get_dai_token_balance()
        assert self.get_dai_vat_balance() == Wad.from_number(153)

    def test_join_not_enough(self):
        # given balances before
        assert self.get_dai_token_balance() == Wad.from_number(84)
        assert self.get_dai_vat_balance() == Wad.from_number(153)

        # when rebalancing without enough tokens to cover the difference
        self.create_keeper(500.0)

        # then ensure all available tokens were joined
        assert self.get_dai_token_balance() == Wad(0)
        assert self.get_dai_vat_balance() == Wad.from_number(237)

    def test_exit_some(self):
        # given balances before
        assert self.get_dai_token_balance() == Wad(0)
        assert self.get_dai_vat_balance() == Wad.from_number(237)

        # when rebalancing to a smaller amount than currently in the vat
        self.create_keeper(200.0)

        # then ensure balances are as expected
        assert self.get_dai_token_balance() == Wad.from_number(37)
        assert self.get_dai_vat_balance() == Wad.from_number(200)

    def test_exit_all(self):
        # given balances before
        assert self.get_dai_token_balance() == Wad.from_number(37)
        assert self.get_dai_vat_balance() == Wad.from_number(200)

        # when rebalancing to 0
        self.create_keeper(0.0)

        # then ensure all dai has been exited
        assert self.get_dai_token_balance() == Wad.from_number(237)
        assert self.get_dai_vat_balance() == Wad(0)


class TestEmptyVatOnExit(TestVatDai):
    def create_keeper(self, exit_dai_on_shutdown: bool, exit_gem_on_shutdown: bool):
        assert isinstance(exit_dai_on_shutdown, bool)
        assert isinstance(exit_gem_on_shutdown, bool)

        vat_dai_behavior = "" if exit_dai_on_shutdown else "--keep-dai-in-vat-on-exit"
        vat_gem_behavior = "" if exit_gem_on_shutdown else "--keep-gem-in-vat-on-exit"

        keeper = AuctionKeeper(args=args(f"--eth-from {self.keeper_address} "
                                         f"--type flop "
                                         f"--network testnet "
                                         f"{vat_dai_behavior} "
                                         f"{vat_gem_behavior} "
                                         f"--model ./bogus-model.sh"), web3=self.web3)
        assert self.web3.eth.defaultAccount == self.keeper_address.address
        assert keeper.arguments.exit_dai_on_shutdown == exit_dai_on_shutdown
        keeper.startup()
        return keeper

    def test_do_not_empty(self):
        # given dai and gem in the vat
        keeper = self.create_keeper(False, False)
        self.purchase_dai(Wad.from_number(153))
        assert self.get_dai_token_balance() >= Wad.from_number(153)
        assert self.mcd.dai_adapter.join(self.keeper_address, Wad.from_number(153)).transact(
            from_address=self.keeper_address)
        wrap_eth(self.mcd, self.keeper_address, Wad.from_number(6))
        # and balances before
        dai_token_balance_before = self.get_dai_token_balance()
        dai_vat_balance_before = self.get_dai_vat_balance()
        gem_token_balance_before = self.get_gem_token_balance()
        gem_vat_balance_before = self.get_gem_vat_balance()

        # when creating and shutting down the keeper
        keeper.shutdown()

        # then ensure no balances changed
        assert dai_token_balance_before == self.get_dai_token_balance()
        assert dai_vat_balance_before == self.get_dai_vat_balance()
        assert gem_token_balance_before == self.get_gem_token_balance()
        assert gem_vat_balance_before == self.get_gem_vat_balance()

    def test_empty_dai_only(self):
        # given balances before
        dai_token_balance_before = self.get_dai_token_balance()
        dai_vat_balance_before = self.get_dai_vat_balance()
        gem_token_balance_before = self.get_gem_token_balance()
        gem_vat_balance_before = self.get_gem_vat_balance()

        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, False)
        keeper.shutdown()

        # then ensure the dai was emptied
        assert self.get_dai_token_balance() == dai_token_balance_before + dai_vat_balance_before
        assert self.get_dai_vat_balance() == Wad(0)
        # and gem was not emptied
        assert gem_token_balance_before == self.get_gem_token_balance()
        assert gem_vat_balance_before == self.get_gem_vat_balance()

    def test_empty_gem_only(self):
        # given gem balances before
        gem_token_balance_before = self.get_gem_token_balance()
        gem_vat_balance_before = self.get_gem_vat_balance()

        # when adding dai
        self.purchase_dai(Wad.from_number(79))
        assert self.mcd.dai_adapter.join(self.keeper_address, Wad.from_number(79)).transact(
            from_address=self.keeper_address)
        dai_token_balance_before = self.get_dai_token_balance()
        dai_vat_balance_before = self.get_dai_vat_balance()
        # and creating and shutting down the keeper
        keeper = self.create_keeper(False, True)
        keeper.shutdown()

        # then ensure dai was not emptied
        assert dai_token_balance_before == self.get_dai_token_balance()
        assert dai_vat_balance_before == self.get_dai_vat_balance()
        # and gem was emptied
        assert gem_token_balance_before == gem_token_balance_before + gem_vat_balance_before
        assert self.get_gem_vat_balance() == Wad(0)

    def test_empty_both(self):
        # when creating and shutting down the keeper
        keeper = self.create_keeper(True, False)
        keeper.shutdown()

        # then ensure the vat is empty
        assert self.get_dai_vat_balance() == Wad(0)
        assert self.get_gem_vat_balance() == Wad(0)
