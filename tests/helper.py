# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus
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
import threading
import time
from contextlib import contextmanager
from io import StringIO

from mock import MagicMock
from web3 import Web3


def args(arguments: str) -> list:
    return arguments.split()


@contextmanager
def captured_output():
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def time_travel_by(web3: Web3, seconds: int):
    assert(isinstance(web3, Web3))
    assert(isinstance(seconds, int))

    if "parity" in web3.version.node.lower():
        print(f"time travel unsupported by parity; waiting {seconds} seconds")
        time.sleep(seconds)
        # force a block mining to have a correct timestamp in latest block
        web3.eth.sendTransaction({'from': web3.eth.accounts[0], 'to': web3.eth.accounts[1], 'value': 1})
    else:
        web3.manager.request_blocking("evm_increaseTime", [seconds])
        # force a block mining to have a correct timestamp in latest block
        web3.manager.request_blocking("evm_mine", [])


def wait_for_other_threads():
    while threading.active_count() > 1:
        time.sleep(0.1)


class TransactionIgnoringTest:
    def start_ignoring_transactions(self):
        self.original_send_transaction = self.web3.eth.sendTransaction
        self.original_get_transaction = self.web3.eth.getTransaction
        self.original_nonce = self.web3.eth.getTransactionCount(self.keeper_address.address)

        self.web3.eth.sendTransaction = MagicMock(return_value='0xaaaaaaaaaabbbbbbbbbbccccccccccdddddddddd')
        self.web3.eth.getTransaction = MagicMock(return_value={'nonce': self.original_nonce})

    def end_ignoring_transactions(self):
        # def second_send_transaction(transaction):
        #     assert transaction['nonce'] == self.original_nonce
        #
        #     # TestRPC doesn't support `sendTransaction` calls with the `nonce` parameter
        #     # (unlike proper Ethereum nodes which handle it very well)
        #     transaction_without_nonce = {key: transaction[key] for key in transaction if key != 'nonce'}
        #     return self.original_send_transaction(transaction_without_nonce)
        #
        # self.web3.eth.sendTransaction = MagicMock(side_effect=second_send_transaction)
        self.web3.eth.sendTransaction = self.original_send_transaction
        self.web3.eth.getTransaction = self.original_get_transaction
