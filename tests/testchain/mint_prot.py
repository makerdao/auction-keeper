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
from tests.conftest import keeper_address, geb, mint_prot, web3

geb = geb(web3())
collateral = geb.collaterals['ETH-C']
keeper_address = keeper_address(web3())

amount = Wad.from_number(float(sys.argv[1]))
assert amount > Wad(0)

mint_prot(geb.prot, keeper_address, amount)

print(f'Minted {str(amount)} protocol tokens, keeper token balance is {str(geb.prot.balance_of(keeper_address))}')
