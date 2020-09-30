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

import sys

from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import keeper_address, geb, other_address, reserve_system_coin, web3

geb = geb(web3())
collateral = geb.collaterals['ETH-C']
keeper_address = keeper_address(web3())
seller = other_address(web3())

amount = Wad.from_number(float(sys.argv[1]))
assert amount > Wad(0)

web3().eth.defaultAccount = seller.address
collateral.approve(seller)
geb.approve_system_coin(seller)

reserve_system_coin(geb, geb.collaterals['ETH-C'], seller, amount, Wad.from_number(2))
assert geb.system_coin_adapter.exit(seller, amount).transact(from_address=seller)
assert geb.system_coin.transfer_from(seller, keeper_address, amount).transact(from_address=seller)
print(f'Purchased {str(amount)} system coin, keeper token balance is {str(geb.system_coin.balance_of(keeper_address))}')
