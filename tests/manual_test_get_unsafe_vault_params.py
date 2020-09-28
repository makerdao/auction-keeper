# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 EdNoepel
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

import os
import sys
from web3 import Web3, HTTPProvider

from pymaker.deployment import DssDeployment
from pymaker.numeric import Wad, Ray, Rad


# This script calculates the amount of collateral needed to produce a vault close to the liquidation ratio.
# Usage: python3 tests/manual_test_get_unsafe_vault_params.py [ILK] ([TARGET_ART])
# If [TARGET_ART] is omitted, the dust cutoff is used.


def r(value, decimals=1):
    return round(float(value), decimals)


web3 = Web3(HTTPProvider(endpoint_uri=os.environ['ETH_RPC_URL'], request_kwargs={"timeout": 10}))
mcd = DssDeployment.from_node(web3)
collateral = mcd.collaterals[str(sys.argv[1])] if len(sys.argv) > 1 else mcd.collaterals['ETH-A']
ilk = collateral.ilk
target_art = Rad.from_number(float(sys.argv[2])) if len(sys.argv) > 2 else ilk.dust
osm_price = collateral.pip.peek()
print(f"{ilk.name} price={osm_price}, mat={r(mcd.spotter.mat(ilk),2)}, spot={ilk.spot}, rate={ilk.rate}")

if osm_price == Wad(0):
    raise ValueError("OSM price is 0; a valid spot price cannot be poked.")

# This accounts for several seconds of rate accumulation between time of calculation and the transaction being mined
flub_amount = Wad(1000)
ink_osm = Wad(target_art / Rad(osm_price) * Rad(mcd.spotter.mat(ilk)) * Rad(ilk.rate)) + flub_amount
ink = Wad(target_art / Rad(ilk.spot) * Rad(ilk.rate)) + flub_amount
if ink_osm != ink:
    print(f"WARNING: ink required using OSM price ({ink_osm}) does not match ink required using spot price ({ink}).")
    print(f"Please poke (mcd -C kovan --ilk={ilk.name} poke) to update spot price.")

# art_actual = Ray(ink) * ilk.spot / ilk.rate
art = Ray(target_art)
collat_ratio = Ray(ink) * Ray(osm_price) / (art * ilk.rate)

print(f"frob with ink={ink} {ilk.name}, art={art} Dai for {r(collat_ratio*100,6)}% collateralization")
