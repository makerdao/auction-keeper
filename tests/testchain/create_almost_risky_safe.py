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
from tests.conftest import create_almost_risky_safe, is_safe_critical, geb, auction_income_recipient_address, web3

geb = geb(web3())
address = auction_income_recipient_address(web3())

collateral_amount = Wad.from_number(float(sys.argv[1])) if len(sys.argv) > 1 else 1.0
collateral = geb.collaterals[str(sys.argv[2])] if len(sys.argv) > 2 else geb.collaterals['ETH-A']
safe = geb.safe_engine.safe(collateral.collateral_type, address)

if is_safe_critical(geb.safe_engine.collateral_type(collateral.collateral_type.name), safe):
    print("Safe is already critical; no action taken")
else:
    create_almost_risky_safe(geb, collateral, Wad.from_number(collateral_amount), address, False)
    print("Created almost risky safe")
