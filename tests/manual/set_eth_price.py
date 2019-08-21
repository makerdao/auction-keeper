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

from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import mcd, set_collateral_price, web3

mcd = mcd(web3())
price = Wad.from_number(float(sys.argv[1])) if len(sys.argv) > 1 else Wad.from_number(200)
ilk_name = str(sys.argv[2]) if len(sys.argv) > 2 else 'ETH-A'
set_collateral_price(mcd, mcd.collaterals[ilk_name], price)
print(f"spot={str(mcd.vat.ilk(ilk_name).spot)[:9]}")
