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

from auction_keeper.gas import UpdatableGasPrice
from auction_keeper.model import Stance, Parameters, Status, Model, ModelFactory
from pyflex import Address, TransactStatus, Transact
from pyflex.numeric import Rad


class Auction:
    logger = logging.getLogger()

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

    def determine_gas_strategy_for_bid(self, model_output, keeper_gas_price):
        # Ensure this auction has a gas strategy assigned
        new_gas_strategy = None
        fixed_gas_price_changed = False
        # if the auction already has a gas strategy...
        if self.gas_price:
            # ...and the model just started supplying gas price
            if model_output.gas_price:
                if isinstance(self.gas_price, UpdatableGasPrice):
                    fixed_gas_price_changed = model_output.gas_price != self.gas_price.gas_price
                else:
                    self.logger.debug(f"Model supplied gas price {model_output.gas_price}, "
                                      f"switching to UpdatableGasPrice for auction {id}")
                    new_gas_strategy = UpdatableGasPrice(model_output.gas_price)
            # ...and the model stopped supplying gas price
            elif not model_output.gas_price and isinstance(self.gas_price, UpdatableGasPrice):
                self.logger.debug(f"Model did not supply gas price; switching to keeper gas strategy for auction {id}")
                new_gas_strategy = keeper_gas_price
        # ...else create the gas strategy relevant to the model
        else:
            # model is supplying gas price
            if model_output.gas_price:
                self.logger.debug(f"Model supplied gas price {model_output.gas_price}, creating UpdatableGasPrice "
                                  f"for auction {id}")
                new_gas_strategy = UpdatableGasPrice(model_output.gas_price)
            # use the keeper's configured gas strategy for the auction
            else:
                self.logger.debug("Model did not supply gas price; using keeper gas strategy")
                new_gas_strategy = keeper_gas_price

        return new_gas_strategy, fixed_gas_price_changed


class Auctions:
    logger = logging.getLogger()

    def __init__(self, collateral_auction_house: Optional[Address], surplus_auction_house: Optional[Address],
                 debt_auction_house: Optional[Address], model_factory: ModelFactory):
        assert isinstance(collateral_auction_house, Address) or (collateral_auction_house is None)
        assert isinstance(surplus_auction_house, Address) or (surplus_auction_house is None)
        assert isinstance(debt_auction_house, Address) or (debt_auction_house is None)
        assert isinstance(collateral_auction_house, Address) or isinstance(surplus_auction_house, Address) or isinstance(debt_auction_house, Address)
        assert isinstance(model_factory, ModelFactory)

        self.auctions = {}
        self.collateral_auction_house = collateral_auction_house
        self.surplus_auction_house = surplus_auction_house
        self.debt_auction_house = debt_auction_house
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
            model_parameters = Parameters(collateral_auction_house=self.collateral_auction_house,
                                          surplus_auction_house=self.surplus_auction_house,
                                          debt_auction_house=self.debt_auction_house,
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

    def __del__(self):
        count = len(self.auctions)
        for id, auction in self.auctions.items():
            try:
                auction.model.terminate()
                del auction.model
            except AssertionError:
                pass
        del self.auctions
        self.logger.debug(f"Removed {count} auctions on shutdown")


class Reservoir:
    # Tracks expenditures on a single round of bid submissions, to prevent submitting bids which will fail because
    # other bids used up the system coin or prot balance (which doesn't update until the transaction is mined).
    def __init__(self, level: Rad):
        assert isinstance(level, Rad)
        self.level = level

    def check_bid_cost(self, id: int, consume: Rad):
        # Lowers the level of the reservoir when system coin or prot is consumed by bids
        assert isinstance(id, int)
        assert isinstance(consume, Rad)

        if self.level > consume:
            self.level -= consume
            return True
        else:
            return False

    def refill(self, produce: Rad):
        # Increases system coin rebalanced during a cost check (not used for prot)
        self.level += produce
