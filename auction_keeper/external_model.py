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


class ExternalModelFactory(ModelFactory):
    def create_model(self) -> Model:
        return ExternalModel()
