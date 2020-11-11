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
from pygasprice_client import EthGasStation, POANetwork, EtherchainOrg, Etherscan, Gasnow

from auction_keeper.gas import DynamicGasPrice
from tests.conftest import get_node_gas_price
from tests.helper import args
import ctypes
import threading
import time


GWEI = 1000000000
default_max_gas = 2000

class TestGasStrategy:
    def teardown_class(self):
        while threading.active_count() > 1:
            for thread in threading.enumerate():
                if thread is not threading.current_thread():
                    print(f"Attempting to kill thread {thread}")
                    sysexit = ctypes.py_object(SystemExit)  # Creates a C pointer to a Python "SystemExit" exception
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), sysexit)
                    time.sleep(2)

    def test_ethgasstation(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--ethgasstation-api-key MY_API_KEY "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, EthGasStation)
        assert keeper.gas_price.gas_station.URL == "https://ethgasstation.info/json/ethgasAPI.json?api-key=MY_API_KEY"

    def test_etherchain(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--etherchain-gas-price "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, EtherchainOrg)
        assert keeper.gas_price.gas_station.URL == "https://www.etherchain.org/api/gasPriceOracle"

    def test_poanetwork(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--poanetwork-gas-price "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, POANetwork)
        assert keeper.gas_price.gas_station.URL == "https://gasprice.poa.network"

        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--poanetwork-gas-price "
                                         f"--poanetwork-url http://localhost:8000 "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, POANetwork)
        assert keeper.gas_price.gas_station.URL == "http://localhost:8000"

    def test_etherscan(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--etherscan-gas-price "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, Etherscan)
        assert keeper.gas_price.gas_station.URL == "https://api.etherscan.io/api?module=gastracker&action=gasoracle"

    def test_etherscan_key(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--etherscan-gas-price "
                                         f"--etherscan-key MY_API_KEY "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, Etherscan)
        assert keeper.gas_price.gas_station.URL == "https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey=MY_API_KEY"

    def test_gasnow(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--gasnow-gas-price "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, Gasnow)
        assert keeper.gas_price.gas_station.URL == "https://www.gasnow.org/api/v3/gas/price"

    def test_gasnow_key(self, geb, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--gasnow-gas-price "
                                         f"--gasnow-app-name MY_APP_NAME "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        assert isinstance(keeper.gas_price.gas_station, Gasnow)
        assert keeper.gas_price.gas_station.URL == "https://www.gasnow.org/api/v3/gas/price?utm_source=MY_APP_NAME"

    def test_default_gas_config(self, web3, keeper_address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type debt --from-block 1 "
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.gas_price, DynamicGasPrice)
        assert keeper.gas_price.initial_multiplier == 1.0
        assert keeper.gas_price.reactive_multiplier == 1.125
        assert keeper.gas_price.gas_maximum == default_max_gas * GWEI

        default_initial_gas = get_node_gas_price(web3)
        assert keeper.gas_price.get_gas_price(0) == default_initial_gas
        assert keeper.gas_price.get_gas_price(31) == default_initial_gas * 1.125
        assert keeper.gas_price.get_gas_price(61) == default_initial_gas * 1.125 ** 2
        assert keeper.gas_price.get_gas_price(91) == default_initial_gas * 1.125 ** 3
        assert keeper.gas_price.get_gas_price(30*80) == default_max_gas * GWEI

    @pytest.mark.skip("This doesn't account for different initial_amounts in our testchains")
    def test_no_api_non_fixed(self, geb, keeper_address):
        c = geb.collaterals['ETH-A']

        reactive_multipler = 1.125 * 3

        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--gas-reactive-multiplier {reactive_multipler} "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        initial_amount = get_node_gas_price(geb.web3)
        assert keeper.gas_price.get_gas_price(0) == initial_amount
        assert keeper.gas_price.get_gas_price(31) == initial_amount * reactive_multipler
        assert keeper.gas_price.get_gas_price(61) == initial_amount * reactive_multipler ** 2
        assert keeper.gas_price.get_gas_price(91) == initial_amount * reactive_multipler ** 3
        assert keeper.gas_price.get_gas_price(30*12) == default_max_gas * GWEI

    def test_fixed_with_explicit_max(self, web3, keeper_address):
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type surplus "
                                         f"--fixed-gas 100 "
                                         f'--gas-maximum 4000 '
                                         f"--model ./bogus-model.sh"), web3=web3)

        assert isinstance(keeper.gas_price, DynamicGasPrice)
        assert keeper.gas_price.fixed_gas == 100 * GWEI
        assert keeper.gas_price.reactive_multiplier == 1.125
        assert keeper.gas_price.gas_maximum == 4000 * GWEI

        assert keeper.gas_price.get_gas_price(0) == 100 * GWEI
        assert keeper.gas_price.get_gas_price(31) == 100 * GWEI * 1.125
        assert keeper.gas_price.get_gas_price(61) == 100 * GWEI * 1.125 ** 2
        assert keeper.gas_price.get_gas_price(91) == 100 * GWEI * 1.125 ** 3
        assert keeper.gas_price.get_gas_price(60*30) == 4000 * GWEI

    def test_config_negative(self, web3, keeper_address):
        with pytest.raises(SystemExit):
            missing_arg = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                   f"--type debt --from-block 1 "
                                                   f"--gas-reactive-multiplier "
                                                   f"--model ./bogus-model.sh"), web3=web3)

        with pytest.raises(SystemExit):
            conflicting_args = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                                   f"--type debt --from-block 1 "
                                                   f"--etherchain-gas-price "
                                                   f"--poanetwork-gas-price "
                                                   f"--model ./bogus-model.sh"), web3=web3)
