# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus, bargst
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

from auction_keeper.model import Stance, Parameters, Status, Model, ModelFactory
from pymaker import Address, TransactStatus, Transact


class Auction:
    def __init__(self, id: int, model: Model):
        assert isinstance(id, int)

        self.model = model
        self.output = None

        self.price = None
        self.gas_price = None
        self.transactions = []

    def register_transaction(self, transact: Transact):
        self.transactions.append(transact)

    def transaction_in_progress(self) -> Optional[Transact]:
        self.transactions = list(filter(lambda transact: transact.status != TransactStatus.FINISHED, self.transactions))

        if len(self.transactions) > 0:
            return self.transactions[-1]

        else:
            return None

    def feed_model(self, input: Status):
        assert isinstance(input, Status)

        self.model.send_status(input)

    def model_output(self) -> Optional[Stance]:
        return self.model.get_stance()


class Auctions:
    logger = logging.getLogger()

    def __init__(self, flipper: Optional[Address], flapper: Optional[Address], flopper: Optional[Address],
                 model_factory: ModelFactory):
        assert isinstance(flipper, Address) or (flipper is None)
        assert isinstance(flapper, Address) or (flapper is None)
        assert isinstance(flopper, Address) or (flopper is None)
        assert isinstance(flipper, Address) or isinstance(flapper, Address) or isinstance(flopper, Address)
        assert isinstance(model_factory, ModelFactory)

        self.auctions = {}
        self.flipper = flipper
        self.flapper = flapper
        self.flopper = flopper
        self.model_factory = model_factory

    # TODO by passing `bid` and `lot` to this method it can actually check if the auction under this id hasn't changed,
    # TODO and restart the model if so.
    def get_auction(self, id: int, create: bool = True) -> Optional[Auction]:
        assert isinstance(id, int)
        assert isinstance(create, bool)

        if create and id not in self.auctions:
            # Log the fact that new auction has been detected
            self.logger.info(f"Started monitoring auction #{id}")

            # Prepare model startup parameters
            model_parameters = Parameters(flipper=self.flipper,
                                          flapper=self.flapper,
                                          flopper=self.flopper,
                                          id=id)

            # Start the model
            model = self.model_factory.create_model(model_parameters)

            # Register new auction
            self.auctions[id] = Auction(id, model)

        return self.auctions.get(id)

    def remove_auction(self, id: int):
        assert isinstance(id, int)

        if id in self.auctions:
            # Stop the model
            self.auctions[id].model.terminate()

            # Remove the auction
            del self.auctions[id]

            # Log the fact that auction has been discarded
            self.logger.info(f"Stopped monitoring auction #{id} as it's not active anymore")
