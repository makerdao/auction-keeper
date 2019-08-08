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

import argparse
import sys

from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import flog_and_heal, mcd, gal_address, web3


parser = argparse.ArgumentParser(prog='create-debt')
parser.add_argument('--print-only', dest='flog_and_heal', action='store_false',
                    help="Just print joy/awe/woe without flogging/healing")
arguments = parser.parse_args(sys.argv[1:])

mcd = mcd(web3())
address = gal_address(web3())

if arguments.flog_and_heal:
    flog_and_heal(web3(), mcd, past_blocks=web3().eth.blockNumber, kiss=False, require_heal=False)

joy = mcd.vat.dai(mcd.vow.address)
awe = mcd.vat.sin(mcd.vow.address)
woe = (awe - mcd.vow.sin()) - mcd.vow.ash()
print(f"joy={str(joy)[:6]}, awe={str(awe)[:9]}, woe={str(woe)[:9]} sump={str(mcd.vow.sump())[:9]}")
