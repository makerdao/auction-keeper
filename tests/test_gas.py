# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 grandizzy
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
from pygasprice_client import EthGasStation, POANetwork, EtherchainOrg

from auction_keeper.gas import DynamicGasPrice
from tests.conftest import get_node_gas_price
from tests.helper import args


GWEI = 1000000000
default_max_gas = 2000
every_secs = 42

class TestGasStrategy:
    def test_ethgasstation(self, mcd, keeper_address):
        # given
        c = mcd.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--ethgasstation-api-key MY_API_KEY "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        assert isinstance(keeper.gas_price.gas_station, EthGasStation)
        assert keeper.gas_price.gas_station.URL == "https://ethgasstation.info/json/ethgasAPI.json?api-key=MY_API_KEY"

    def test_etherchain(self, mcd, keeper_address):
        # given
        c = mcd.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--etherchain-gas-price "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        assert isinstance(keeper.gas_price.gas_station, EtherchainOrg)
        assert keeper.gas_price.gas_station.URL == "https://www.etherchain.org/api/gasPriceOracle"

    def test_poanetwork(self, mcd, keeper_address):
        # given
        c = mcd.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--poanetwork-gas-price "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        assert isinstance(keeper.gas_price.gas_station, POANetwork)
        assert keeper.gas_price.gas_station.URL == "https://gasprice.poa.network"

        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--poanetwork-gas-price "
                                         f"--poanetwork-url http://localhost:8000 "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        assert isinstance(keeper.gas_price.gas_station, POANetwork)
        assert keeper.gas_price.gas_station.URL == "http://localhost:8000"

    def test_default_gas_config(self, web3, keeper_address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flop --from-block 1 "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.gas_price, DynamicGasPrice)
        assert keeper.gas_price.initial_multiplier == 1.0
        assert keeper.gas_price.reactive_multiplier == 1.125
        assert keeper.gas_price.gas_maximum == default_max_gas * GWEI

        default_initial_gas = get_node_gas_price(web3)
        assert keeper.gas_price.get_gas_price(0) == default_initial_gas
        assert keeper.gas_price.get_gas_price(1 + every_secs) == default_initial_gas * 1.125
        assert keeper.gas_price.get_gas_price(1 + every_secs * 2) == default_initial_gas * 1.125 ** 2
        assert keeper.gas_price.get_gas_price(1 + every_secs * 3) == default_initial_gas * 1.125 ** 3
        assert keeper.gas_price.get_gas_price(every_secs * 80) == default_max_gas * GWEI

    def test_no_api_non_fixed(self, mcd, keeper_address):
        c = mcd.collaterals['ETH-A']

        reactive_multipler = 1.125 * 3

        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--gas-reactive-multiplier {reactive_multipler} "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        initial_amount = get_node_gas_price(mcd.web3)
        assert keeper.gas_price.get_gas_price(0) == initial_amount
        assert keeper.gas_price.get_gas_price(1 + every_secs) == initial_amount * reactive_multipler
        assert keeper.gas_price.get_gas_price(1 + every_secs * 2) == initial_amount * reactive_multipler ** 2
        assert keeper.gas_price.get_gas_price(1 + every_secs * 3) == initial_amount * reactive_multipler ** 3
        assert keeper.gas_price.get_gas_price(every_secs * 12) == default_max_gas * GWEI

    def test_fixed_with_explicit_max(self, web3, keeper_address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flap "
                                         f"--fixed-gas 100 "
                                         f'--gas-maximum 4000 '
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.gas_price, DynamicGasPrice)
        assert keeper.gas_price.fixed_gas == 100 * GWEI
        assert keeper.gas_price.reactive_multiplier == 1.125
        assert keeper.gas_price.gas_maximum == 4000 * GWEI

        assert keeper.gas_price.get_gas_price(0) == 100 * GWEI
        assert keeper.gas_price.get_gas_price(1 + every_secs) == 100 * GWEI * 1.125
        assert keeper.gas_price.get_gas_price(1 + every_secs * 2) == 100 * GWEI * 1.125 ** 2
        assert keeper.gas_price.get_gas_price(1 + every_secs * 3) == 100 * GWEI * 1.125 ** 3
        assert keeper.gas_price.get_gas_price(every_secs * 60) == 4000 * GWEI

    def test_config_negative(self, web3, keeper_address):
        with pytest.raises(SystemExit):
            missing_arg = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                   f"--type flop --from-block 1 "
                                                   f"--gas-reactive-multiplier "
                                                   f"--model ./bogus-model.sh"), web3=web3)

        with pytest.raises(SystemExit):
            conflicting_args = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                   f"--type flop --from-block 1 "
                                                   f"--etherchain-gas-price "
                                                   f"--poanetwork-gas-price "
                                                   f"--model ./bogus-model.sh"), web3=web3)
