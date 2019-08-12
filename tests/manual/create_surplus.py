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

from pymaker.approval import hope_directly
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import create_cdp_with_surplus, flog_and_heal, mcd, gal_address, reserve_dai, simulate_frob, web3, wrap_eth


mcd = mcd(web3())
address = gal_address(web3())


def create_cdp_with_surplus():
    c = mcd.collaterals[0]
    ilk = mcd.vat.ilk(c.ilk.name)
    dink = Wad.from_number(1000)

    wrap_eth(mcd, address, dink)
    c.approve(address)
    assert c.adapter.join(address, dink).transact(from_address=address)

    dart = (dink * Wad(ilk.spot)) * Wad.from_number(0.9)
    simulate_frob(mcd, c, address, dink, dart)
    assert mcd.vat.frob(c.ilk, address, dink=dink, dart=dart).transact(from_address=address)

    assert mcd.jug.drip(c.ilk).transact(from_address=address)


create_cdp_with_surplus()
flog_and_heal(web3(), mcd, past_blocks=web3().eth.blockNumber, kiss=False, require_heal=True)
