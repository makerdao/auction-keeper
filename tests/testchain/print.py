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

from pprint import pprint
from pymaker.numeric import Wad, Ray, Rad
from tests.conftest import flog_and_heal, mcd, gal_address, web3


parser = argparse.ArgumentParser(prog='print')
parser.add_argument('--balances', dest='balances', action='store_true', default=False,
                    help="Print surplus and debt balances in the Vow")
parser.add_argument('--auctions', dest='auctions', action='store_true', default=False,
                    help="Dump auction details")
parser.add_argument('--missed-flops', dest='missed_flops', action='store_true', default=False,
                    help="List flops which were not bid upon")
arguments = parser.parse_args(sys.argv[1:])

mcd = mcd(web3())
address = gal_address(web3())


def print_balances():
    joy = mcd.vat.dai(mcd.vow.address)
    awe = mcd.vat.sin(mcd.vow.address)
    woe = (awe - mcd.vow.sin()) - mcd.vow.ash()
    print(f"joy={str(joy)[:6]}, awe={str(awe)[:9]}, woe={str(woe)[:9]}, "
          f"Sin={str(mcd.vow.sin())[:9]}, Ash={str(mcd.vow.ash())[:9]}, "
          f"debt={str(mcd.vat.debt())[:9]}, vice={str(mcd.vat.vice())[:9]}")
          #f"bump={str(mcd.vow.bump())[:9]}, sump={str(mcd.vow.sump())[:9]}")


def print_auctions():
    pprint(mcd.active_auctions())


def print_missed_flops():
    total = 0
    for i in range(mcd.flopper.kicks()):
        auction = mcd.flopper.bids(i)
        if auction.bid != Rad(0):
            total += 1
            print(f"id={i}, bid={auction.bid}, lot={auction.lot}, guy={auction.guy}")
    print(f"{total} flops were missed, accounting for {str(mcd.vow.sump()*total)[:9]} Dai in debt")

if arguments.balances:
    print_balances()
if arguments.auctions:
    print_auctions()
if arguments.missed_flops:
    print_missed_flops()
