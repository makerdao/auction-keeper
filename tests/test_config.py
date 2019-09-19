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
from pymaker import Address
from pymaker.auctions import Flipper, Flapper, Flopper
from pymaker.dss import Cat, DaiJoin, GemJoin, Vow
from pymaker.token import DSToken
from tests.helper import args


class TestConfig:
    def test_flip_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--network testnet "
                                         f"--ilk ZRX-A "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flipper, Flipper)
        assert keeper.collateral.flipper == keeper.flipper
        assert keeper.collateral.ilk.name == 'ZRX-A'
        assert keeper.flapper is None
        assert keeper.flopper is None
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.gem_join, GemJoin)

    def test_flip_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(RuntimeError) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flip "
                                    f"--network testnet "
                                    f"--model ./bogus-model.sh"), web3=web3)
        assert "ilk" in str(e)

    def test_flap_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flap "
                                         f"--network testnet "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flapper, Flapper)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.mkr, DSToken)
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.vow, Vow)

    def test_flap_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(SystemExit) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flap "
                                    f"--model ./bogus-model.sh"), web3=web3)

    def test_flop_keeper(self, web3, keeper_address: Address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flop "
                                         f"--network testnet "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.flopper, Flopper)
        assert isinstance(keeper.dai_join, DaiJoin)
        assert isinstance(keeper.mkr, DSToken)
        assert isinstance(keeper.cat, Cat)
        assert isinstance(keeper.vow, Vow)

    def test_flop_keeper_negative(self, web3, keeper_address: Address):
        with pytest.raises(SystemExit) as e:
            AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                    f"--type flap "
                                    f"--model ./bogus-model.sh"), web3=web3)
