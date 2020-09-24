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
from typing import Optional, Tuple
from web3 import Web3

from auction_keeper.model import Status
from pyflex import Address, Transact
from pyflex.approval import directly, approve_safe_modification_directly
from pyflex.auctions import AuctionContract, PreSettlementSurplusAuctionHouse, DebtAuctionHouse
from pyflex.auctions import EnglishCollateralAuctionHouse, FixedDiscountCollateralAuctionHouse
from pyflex.gas import GasPrice
from pyflex.numeric import Wad, Ray, Rad


def era(web3: Web3):
    return web3.eth.getBlock('latest')['timestamp']


class Strategy:
    logger = logging.getLogger()

    def __init__(self, contract: AuctionContract):
        assert isinstance(contract, AuctionContract)
        self.contract = contract

    def approve(self, gas_price: GasPrice):
        raise NotImplementedError

    def get_input(self, id: int):
        raise NotImplementedError

    def settle_auction(self, id: int) -> Transact:
        return self.contract.settle_auction(id)

    def restart_auction(self, id: int) -> Transact:
        return self.contract.restart_auction(id)


class EnglishCollateralAuctionStrategy(Strategy):
    def __init__(self, collateral_auction_house: EnglishCollateralAuctionHouse, min_amount_to_sell: Wad):
        assert isinstance(collateral_auction_house, EnglishCollateralAuctionHouse)
        assert isinstance(min_amount_to_sell, Wad)
        super().__init__(collateral_auction_house)

        self.collateral_auction_house = collateral_auction_house
        self.bid_increase = collateral_auction_house.bid_increase()
        self.min_amount_to_sell = min_amount_to_sell

    def approve(self, gas_price: GasPrice):
        assert isinstance(gas_price, GasPrice)
        #self.collateral_auction_house.approve(self.collateral_auction_house.safe_engine(), approve_safe_modification_directly(gas_price=gas_price))
        self.collateral_auction_house.approve(self.collateral_auction_house.safe_engine(), approve_safe_modification_directly())

    def auctions_started(self) -> int:
        return self.collateral_auction_house.auctions_started()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.collateral_auction_house.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      collateral_auction_house=self.collateral_auction_house.address,
                      surplus_auction_house=None,
                      debt_auction_house=None,
                      bid_amount=bid.bid_amount,  # Rad
                      amount_to_sell=bid.amount_to_sell,  # Wad
                      amount_to_raise=bid.amount_to_raise,
                      bid_increase=self.bid_increase,
                      high_bidder=bid.high_bidder,
                      era=era(self.collateral_auction_house.web3),
                      bid_expiry=bid.bid_expiry,
                      auction_deadline=bid.auction_deadline,
                      price=Wad(bid.bid_amount / Rad(bid.amount_to_sell)) if bid.amount_to_sell != Wad(0) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.collateral_auction_house.bids(id)

        # decreaseSoldAmount phase
        if bid.bid_amount == bid.amount_to_raise:
            our_amount = Wad(bid.bid_amount / Rad(price))
            if our_amount < self.min_amount_to_sell:
                self.logger.debug(f"decreaseSoldAmount lot {our_amount} less than minimum {self.min_amount_to_sell} for auction {id}")
                return None, None, None

            if (our_amount * self.bid_increase <= bid.amount_to_sell) and (our_amount < bid.amount_to_sell):
                return price, self.collateral_auction_house.decrease_sold_amount(id, our_amount, bid.bid_amount), bid.bid_amount
            else:
                self.logger.debug(f"decreaseSoldAmount lot {our_amount} would not exceed the bid increment for auction {id}")
                return None, None, None

        # increaseBidSize phase
        else:
            if bid.amount_to_sell < self.min_amount_to_sell:
                self.logger.debug(f"increaseBidSize lot {bid.amount_to_sell} less than minimum {self.min_amount_to_sell} for auction {id}")
                return None, None, None

            our_bid = Rad.min(Rad(bid.amount_to_sell) * price, bid.amount_to_raise)
            our_price = price if our_bid < bid.amount_to_raise else Wad(bid.bid_amount) / bid.amount_to_sell

            if (our_bid >= bid.bid_amount * self.bid_increase or our_bid == bid.amount_to_raise) and our_bid > bid.bid_amount:
                return our_price, self.collateral_auction_house.increase_bid_size(id, bid.amount_to_sell, our_bid), our_bid
            else:
                self.logger.debug(f"increaseBidSize bid {our_bid} would not exceed the bid increment for auction {id}")
                return None, None, None


class SurplusAuctionStrategy(Strategy):
    def __init__(self, surplus_auction_house: PreSettlementSurplusAuctionHouse, prot: Address):
        assert isinstance(surplus_auction_house, PreSettlementSurplusAuctionHouse)
        assert isinstance(prot, Address)
        super().__init__(surplus_auction_house)

        self.surplus_auction_house = surplus_auction_house
        self.bid_increase = surplus_auction_house.bid_increase()
        self.prot = prot

    def approve(self, gas_price: GasPrice):
        self.surplus_auction_house.approve(self.prot, directly(gas_price=gas_price))

    def auctions_started(self) -> int:
        return self.surplus_auction_house.auctions_started()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.surplus_auction_house.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      collateral_auction_house=None,
                      surplus_auction_house=self.surplus_auction_house.address,
                      debt_auction_house=None,
                      bid_amount=bid.bid_amount,
                      amount_to_sell=bid.amount_to_sell,
                      amount_to_raise=None,
                      bid_increase=self.bid_increase,
                      high_bidder=bid.high_bidder,
                      era=era(self.surplus_auction_house.web3),
                      bid_expiry=bid.bid_expiry,
                      auction_deadline=bid.auction_deadline,
                      price=Wad(bid.amount_to_sell / Rad(bid.bid_amount)) if bid.bid_amount != Wad(0) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.surplus_auction_house.bids(id)
        our_bid = bid.amount_to_sell / Rad(price)

        if our_bid >= Rad(bid.bid_amount) * Rad(self.bid_increase) and our_bid > Rad(bid.bid_amount):
            return price, self.surplus_auction_house.increase_bid_size(id, bid.amount_to_sell, Wad(our_bid)), Rad(our_bid)
        else:
            self.logger.debug(f"bid {our_bid} would not exceed the bid increment for auction {id}")
            return None, None, None


class DebtAuctionStrategy(Strategy):
    def __init__(self, debt_auction_house: DebtAuctionHouse):
        assert isinstance(debt_auction_house, DebtAuctionHouse)
        super().__init__(debt_auction_house)

        self.debt_auction_house = debt_auction_house
        self.bid_increase = debt_auction_house.bid_decrease()

    def approve(self, gas_price: GasPrice):
        self.debt_auction_house.approve(self.debt_auction_house.safe_engine(), approve_safe_modification_directly(gas_price=gas_price))

    def auctions_started(self) -> int:
        return self.debt_auction_house.auctions_started()

    def get_input(self, id: int) -> Status:
        assert isinstance(id, int)

        # Read auction state
        bid = self.debt_auction_house.bids(id)

        # Prepare the model input from auction state
        return Status(id=id,
                      collateral_auction_house=None,
                      surplus_auction_house=None,
                      debt_auction_house=self.debt_auction_house.address,
                      bid_amount=bid.bid_amount,
                      amount_to_sell=bid.amount_to_sell,
                      amount_to_raise=None,
                      bid_increase=self.bid_increase,
                      high_bidder=bid.high_bidder,
                      era=era(self.debt_auction_house.web3),
                      bid_expiry=bid.bid_expiry,
                      auction_deadline=bid.auction_deadline,
                      price=Wad(bid.bid_amount / Rad(bid.amount_to_sell)) if Wad(bid.bid_amount) != Wad(0) else None)

    def bid(self, id: int, price: Wad) -> Tuple[Optional[Wad], Optional[Transact], Optional[Rad]]:
        assert isinstance(id, int)
        assert isinstance(price, Wad)

        bid = self.debt_auction_house.bids(id)
        our_amount = bid.bid_amount / Rad(price)

        if Ray(our_amount) * self.bid_increase <= Ray(bid.amount_to_sell) and our_amount < Rad(bid.amount_to_sell):
            return price, self.debt_auction_house.decrease_sold_amount(id, Wad(our_amount), bid.bid_amount), bid.bid_amount
        else:
            self.logger.debug(f"our_amount {our_amount} would not exceed the bid increment for auction {id}")
            return None, None, None
