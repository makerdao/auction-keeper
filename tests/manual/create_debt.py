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
from tests.conftest import flog_and_heal, mcd, gal_address, web3


mcd = mcd(web3())
address = gal_address(web3())

# Test some flip auctions to build debt before calling this.

flog_and_heal(web3(), mcd, past_blocks=web3().eth.blockNumber, kiss=False, require_heal=False)
print("flog_and_heal completed")

