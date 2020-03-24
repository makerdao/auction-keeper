# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2020 reverendus, EdNoepel
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

import asyncio
import sys
import logging
import threading
import time
from contextlib import contextmanager
from io import StringIO
from mock import MagicMock
from pymaker import Wad
from web3 import Web3


from pymaker import Receipt, Transact


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

    if "parity" in web3.clientVersion.lower():
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
        asyncio.sleep(0.3)


class TransactionIgnoringTest:
    class MockReceipt(Receipt):
        def __init__(self):
            super().__init__({
                'transactionHash': '0xaaaaaaaaaabbbbbbbbbbccccccccccdddddddddd',
                'gasUsed': 12345,
                'logs': []
            })
            self.successful = True

    def start_ignoring_transactions(self):
        """ Allows an async tx to be created and leaves it trapped in Transact's event loop """
        self.original_send_transaction = self.web3.eth.sendTransaction
        self.original_get_transaction = self.web3.eth.getTransaction
        self.original_tx_count = self.web3.eth.getTransactionCount
        self.original_nonce = self.web3.eth.getTransactionCount(self.keeper_address.address)

        self.web3.eth.sendTransaction = MagicMock(return_value='0xaaaaaaaaaabbbbbbbbbbccccccccccdddddddddd')
        self.web3.eth.getTransaction = MagicMock(return_value={'nonce': self.original_nonce})
        self.web3.eth.getTransactionCount = MagicMock(return_value=0)

        logging.debug(f"Started ignoring async transactions at nonce {self.original_nonce}")

    def end_ignoring_transactions(self, ensure_next_tx_is_replacement=True):
        """ Stops trapping an async tx, with a facility to ensure the next tx is a replacement (where desired) """
        def second_send_transaction(transaction):
            # Ensure the second transaction gets sent with the same nonce, replacing the first transaction.
            assert transaction['nonce'] == self.original_nonce
            # Restore original behavior for the third transaction.
            self.web3.eth.sendTransaction = self.original_send_transaction

            # TestRPC doesn't support `sendTransaction` calls with the `nonce` parameter
            # (unlike proper Ethereum nodes which handle it very well)
            transaction_without_nonce = {key: transaction[key] for key in transaction if key != 'nonce'}
            return self.original_send_transaction(transaction_without_nonce)

        # Give the previous Transact a chance to enter its event loop
        time.sleep(0.1)

        if ensure_next_tx_is_replacement:
            self.web3.eth.sendTransaction = MagicMock(side_effect=second_send_transaction)
        else:
            self.web3.eth.sendTransaction = self.original_send_transaction
        self.web3.eth.getTransaction = self.original_get_transaction
        self.web3.eth.getTransactionCount = self.original_tx_count

        logging.debug("Finished ignoring async transactions")

    def start_ignoring_sync_transactions(self):
        """ Mocks submission of a tx, prentending it happened """
        self.original_tx_count = self.web3.eth.getTransactionCount
        self.original_get_receipt = Transact._get_receipt
        self.original_func = Transact._func

        Transact._get_receipt = MagicMock(return_value=TransactionIgnoringTest.MockReceipt())
        Transact._func = MagicMock(return_value='0xccccccccccddddddddddaaaaaaaaaabbbbbbbbbb')
        self.web3.eth.getTransactionCount = MagicMock(return_value=9999999999)
        logging.debug("Started ignoring sync transactions")

    def end_ignoring_sync_transactions(self):
        self.web3.eth.getTransactionCount = self.original_tx_count
        Transact._get_receipt = self.original_get_receipt
        Transact._func = self.original_func
        logging.debug("Finished ignoring sync transactions")
