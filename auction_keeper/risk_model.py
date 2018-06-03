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

from threading import RLock
from typing import Optional

from auction_keeper.model import ModelParameters, ModelOutput, ModelInput
from pymaker import Wad, Address


class Model:
    def read(self) -> Optional[ModelOutput]:
        raise NotImplementedError

    def write(self, input: ModelInput):
        raise NotImplementedError

    def start(self, parameters: ModelParameters):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class ModelFactory:
    def create_model(self) -> Model:
        raise NotImplementedError
