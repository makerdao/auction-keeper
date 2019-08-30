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
from tests.conftest import mcd, gal_address, simulate_frob, web3, wrap_eth


mcd = mcd(web3())
address = gal_address(web3())


def create_cdp_with_surplus():
    c = mcd.collaterals['ETH-A']
    ilk = mcd.vat.ilk(c.ilk.name)
    dink = Wad.from_number(float(sys.argv[1]))

    wrap_eth(mcd, address, dink)
    c.approve(address)
    assert c.adapter.join(address, dink).transact(from_address=address)

    dart = (dink * Wad(ilk.spot)) * Wad.from_number(0.99)
    simulate_frob(mcd, c, address, dink, dart)
    assert mcd.vat.frob(c.ilk, address, dink=dink, dart=dart).transact(from_address=address)

    assert mcd.jug.drip(c.ilk).transact(from_address=address)


create_cdp_with_surplus()
