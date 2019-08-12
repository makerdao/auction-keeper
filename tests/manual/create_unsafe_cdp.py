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

from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import create_unsafe_cdp, is_cdp_safe, mcd, gal_address, web3

mcd = mcd(web3())
collateral = mcd.collaterals[2]
address = gal_address(web3())

urn = mcd.vat.urn(collateral.ilk, address)
if not is_cdp_safe(mcd.vat.ilk(collateral.ilk.name), urn):
    print("CDP is already unsafe; no action taken")
else:
    create_unsafe_cdp(mcd, collateral, Wad.from_number(1), address)
    print("Created unsafe CDP")
