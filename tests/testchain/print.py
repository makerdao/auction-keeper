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
from pyflex.numeric import Wad, Ray, Rad
from tests.conftest import pop_debt_and_settle_debt, geb, auction_income_recipient_address, web3


parser = argparse.ArgumentParser(prog='print')
parser.add_argument('--balances', dest='balances', action='store_true', default=False,
                    help="Print surplus and debt balances in the Accounting Engine")
parser.add_argument('--auctions', dest='auctions', action='store_true', default=False,
                    help="Dump auction details")
parser.add_argument('--missed-debt-auctions', dest='missed_debt_auctions', action='store_true', default=False,
                    help="List debt auctions which were not bid upon")
arguments = parser.parse_args(sys.argv[1:])

geb = geb(web3())
address = auction_income_recipient_address(web3())


def print_balances():
    total_surplus = geb.safe_engine.coin_balance(geb.accounting_engine.address)
    total_debt = geb.safe_engine.debt_balance(geb.accounting_engine.address)
    unqueued_unauctioned_debt = (total_debt - geb.accounting_engine.total_queued_debt()) - geb.accounting_engine.total_on_auction_debt()
    print(f"total_surplus={str(total_surplus)[:6]}, total_debt={str(total_debt)[:9]}, "
          f"unqueued_unauctioned_debt={str(unqueued_unauctioned_debt)[:9]}, "
          f"total_queued_debt={str(geb.accounting_engine.total_queued_debt())[:9]}, "
          f"total_on_auction_debt={str(geb.accounting_engine.total_on_auction_debt())[:9]}, "
          f"global_debt={str(geb.safe_engine.global_debt())[:9]}, "
          f"global_unbacked_debt={str(geb.safe_engine.global_unbacked_debt())[:9]}")

def print_auctions():
    pprint(geb.active_auctions())

def print_missed_debt_auctions():
    total = 0
    for i in range(geb.debt_auction_house.auctions_started()):
        auction = geb.debt_auction_house.bids(i)
        if auction.bid_amount != Rad(0):
            total += 1
            print(f"id={i}, bid={auction.bid}, lot={auction.lot}, guy={auction.guy}")
    print(f"{total} debt auctions were missed, accounting for {str(geb.accounting_engine.debt_auction_bid_size()*total)[:9]} system coin in debt")

if arguments.balances:
    print_balances()
if arguments.auctions:
    print_auctions()
if arguments.missed_debt_auctions:
    print_missed_debt_auctions()
