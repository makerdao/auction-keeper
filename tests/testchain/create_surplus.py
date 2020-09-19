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
from tests.conftest import geb, auction_income_recipient_address, web3, wrap_eth


geb = geb(web3())
address = auction_income_recipient_address(web3())

def create_safe_with_surplus():
    c = geb.collaterals['ETH-A']
    collateral_type = geb.safe_engine.collateral_type(c.collateral_type.name)
    delta_collateral = Wad.from_number(float(sys.argv[1]))

    wrap_eth(mcd, address, delta_collateral)
    c.approve(address)
    assert c.adapter.join(address, delta_collateral).transact(from_address=address)

    delta_debt = (delta_collateral * Wad(collateral_type.spot)) * Wad.from_number(0.99)
    assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, address, delta_collateral=delta_collateral, delta_debt=delta_debt).transact(from_address=address)

    assert geb.tax_collector.tax_single(c.collateral_type).transact(from_address=address)


create_safe_with_surplus()
