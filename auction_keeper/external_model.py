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

from auction_keeper.risk_model import ModelFactory, Model


class ExternalModel(Model):
    pass

    #TODO implement subprocess communication, killing etc. here
    #as in:
    #
    # def __init__(self, contract_address: Address, api_server: str, logger: Logger):
    #     assert(isinstance(contract_address, Address))
    #     assert(isinstance(api_server, str))
    #     assert(isinstance(logger, Logger))
    #
    #     self.contract_address = contract_address
    #     self.api_server = api_server
    #     self.logger = logger
    #     self.thread = threading.Thread(target=self._run, daemon=True)
    #     self.thread.start()
    #
    # def _run(self):
    #     self.process = Popen(['node', 'main.js', self.api_server], cwd='utils/etherdelta-socket',
    #                          stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
    #     self._set_nonblock(self.process.stdout)
    #     self._set_nonblock(self.process.stderr)
    #
    #     while True:
    #         try:
    #             lines = read(self.process.stdout.fileno(), 1024).decode('utf-8').splitlines()
    #             for line in lines:
    #                 self.logger.info(f"EtherDelta interface: {line}")
    #         except OSError:
    #             pass  # the os throws an exception if there is no data
    #
    #         try:
    #             lines = read(self.process.stderr.fileno(), 1024).decode('utf-8').splitlines()
    #             for line in lines:
    #                 self.logger.info(f"EtherDelta interface error: {line}")
    #         except OSError:
    #             pass  # the os throws an exception if there is no data
    #
    #         time.sleep(0.1)
    #
    # @staticmethod
    # def _set_nonblock(pipe):
    #     flags = fcntl(pipe, F_GETFL) # get current p.stdout flags
    #     fcntl(pipe, F_SETFL, flags | O_NONBLOCK)
    #
    # def publish_offchain_order(self, order: OffChainOrder):
    #     assert(isinstance(order, OffChainOrder))
    #
    #     self.logger.info(f"Sending off-chain EtherDelta order {order}")
    #
    #     self.process.stdin.write((json.dumps(order.to_json(self.contract_address)) + '\n').encode('ascii'))
    #     self.process.stdin.flush()
    #
    # def __repr__(self):
    #     return f"EtherDeltaApi()"


class ExternalModelFactory(ModelFactory):
    def create_model(self) -> Model:
        return ExternalModel()
