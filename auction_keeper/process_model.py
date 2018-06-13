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

import logging
from typing import Optional

from auction_keeper.model import ModelParameters, ModelInput, ModelOutput
from auction_keeper.process import Process
from pymaker import Wad


class Model:
    logger = logging.getLogger()

    def __init__(self, command: str, parameters: ModelParameters):
        assert(isinstance(command, str))
        assert(isinstance(parameters, ModelParameters))

        self._command = command
        self._arguments = f"--id {parameters.id}"
        self._arguments += f" --flipper {parameters.flipper}" if parameters.flipper is not None else ""
        self._arguments += f" --flapper {parameters.flapper}" if parameters.flapper is not None else ""
        self._arguments += f" --flopper {parameters.flopper}" if parameters.flopper is not None else ""
        self._last_output = None

        self.logger.info(f"Instantiated model '{self._command} {self._arguments}'")

        self._process = Process(f"{self._command} {self._arguments}")
        self._process.start()

    def _ensure_process_running(self):
        if not self._process.running:
            self.logger.warning(f"Model process '{self._command} {self._arguments}' is down, restarting it")

            self._process.start()

    def input(self, input: ModelInput):
        assert(isinstance(input, ModelInput))

        self._ensure_process_running()

        self._process.write({
            "bid": str(input.bid),
            "lot": str(input.lot),
            "beg": str(input.beg),
            "guy": str(input.guy),
            "era": int(input.era),
            "tic": int(input.tic),
            "end": int(input.end),
            "price": str(input.price),
        })

    def output(self) -> Optional[ModelOutput]:
        self._ensure_process_running()

        while True:
            data = self._process.read()

            if data is not None:
                self._last_output = ModelOutput(price=Wad.from_number(data['price']),
                                                gas_price=int(data['gasPrice']) if 'gasPrice' in data else None)

            else:
                break

        return self._last_output

    def terminate(self):
        self.logger.info(f"Terminating model '{self._command} {self._arguments}'")

        self._process.stop()


class ModelFactory:
    def __init__(self, command: str):
        assert(isinstance(command, str))

        self.command = command

    def create_model(self, parameters: ModelParameters) -> Model:
        return Model(self.command, parameters)
