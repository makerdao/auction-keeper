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

from auction_keeper.main import AuctionKeeper
from pygasprice_client import EthGasStation, POANetwork, EtherchainOrg

from tests.helper import args


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

    def test_increasing(self, mcd, keeper_address):
        # given
        c = mcd.collaterals['ETH-A']
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type flip "
                                         f"--from-block 1 "
                                         f"--ilk {c.ilk.name} "
                                         f"--model ./bogus-model.sh"), web3=mcd.web3)
        assert keeper.gas_price.get_gas_price(0) == 5*1000000000
        assert keeper.gas_price.get_gas_price(61) == 5*1000000000+10*1000000000
        assert keeper.gas_price.get_gas_price(60000) == 100*1000000000


