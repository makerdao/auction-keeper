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

from auction_keeper.gas import DynamicGasPrice
from tests.conftest import get_node_gas_price, wrap_eth
from tests.helper import args
import time
from pyflex import Address
from pyflex.numeric import Wad
from pyflex.model import Token
from pyexchange.uniswapv2 import UniswapV2


class TestUniswap:

    def test_uniswap(self, web3, geb, keeper_address):
        # given
        slippage = 0.97
        collateral = geb.collaterals['ETH-A']


        token_syscoin = Token("PRAI", Address(geb.system_coin.address), 18)
        token_weth = Token("WETH", collateral.collateral.address, 18)
        weth_syscoin_list = [token_weth, geb.system_coin]
        weth_syscoin_path = [token_weth.address.address, geb.system_coin.address.address]
        syscoin_weth_path = weth_syscoin_path[::-1]

        syscoin_eth_uniswap = UniswapV2(web3, token_syscoin, token_weth, keeper_address,
					     geb.uniswap_router, geb.uniswap_factory)

        exchange_rate = syscoin_eth_uniswap.get_exchange_rate()

        syscoin_eth_uniswap.approve(token_syscoin)
        syscoin_eth_uniswap.approve(token_weth)

        collateral_amount = Wad.from_number(5)
        wrap_eth(geb, keeper_address, collateral_amount)
        
        min_amount_out = collateral_amount / exchange_rate * Wad.from_number(slippage)
        assert syscoin_eth_uniswap.swap_exact_eth_for_tokens(collateral_amount, min_amount_out, weth_syscoin_path).transact()
