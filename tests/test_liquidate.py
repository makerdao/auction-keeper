# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 bargst, EdNoepel
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

import pytest

from auction_keeper.main import AuctionKeeper
from pyflex.approval import approve_safe_modification_directly
from pyflex.numeric import Wad, Ray, Rad
from pyflex.auctions import EnglishCollateralAuctionHouse, FixedDiscountCollateralAuctionHouse

from tests.conftest import web3, geb, create_critical_safe, keeper_address, reserve_system_coin, purchase_system_coin, \
                           set_collateral_price
from tests.helper import args, time_travel_by, TransactionIgnoringTest, wait_for_other_threads


@pytest.mark.timeout(60)
class TestAuctionKeeperLiquidate(TransactionIgnoringTest):
    def test_liquidation_and_collateral_auction(self, web3, geb, auction_income_recipient_address, keeper_address):
        # given
        c = geb.collaterals['ETH-A']
        set_collateral_price(geb, c, Wad.from_number(500))
        keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                         f"--type collateral "
                                         f"--from-block 1 "
                                         f"--collateral-type {c.collateral_type.name} "
                                         f"--model ./bogus-model.sh"), web3=geb.web3)
        keeper.approve()
        unsafe_safe = create_critical_safe(geb, c, Wad.from_number(1.2), auction_income_recipient_address)
        assert len(geb.active_auctions()["collateral_auctions"][c.collateral_type.name]) == 0

        # Keeper won't bid with a 0 system coin balance
        purchase_system_coin(Wad.from_number(20), keeper_address)
        assert geb.system_coin_adapter.join(keeper_address, Wad.from_number(20)).transact(from_address=keeper_address)

        # when
        keeper.check_safes()
        print("Done checking safes")
        wait_for_other_threads()
        print("after wait for other threads")

        # then
        #print(geb.liquidation_engine.past_liquidations(10))
        assert len(geb.liquidation_engine.past_liquidations(10)) > 0
        safe = geb.safe_engine.safe(unsafe_safe.collateral_type, unsafe_safe.address)
        assert safe.generated_debt == Wad(0)  # unsafe safe has been liquidated
        assert safe.locked_collateral == Wad(0)  # unsafe safe is now safe ...
        assert c.collateral_auction_house.auctions_started() == 1  # One auction started

    @pytest.mark.skip("failing")
    def test_should_not_liquidate_dusty_safes(self, geb, auction_income_recipient_address):
        # given a lot smaller than the dust limit
        c = geb.collaterals['ETH-A']
        safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
        assert safe.generated_debt < Wad(c.collateral_type.debt_floor)
        auctions_before = c.collateral_auction_house.auctions_started()

        # when a small unsafe safe is created
        assert not geb.liquidation_engine.can_liquidate(c.collateral_type, safe)

        # then ensure the keeper does not liquidate it
        self.keeper.check_safes()
        wait_for_other_threads()
        auctions_after = c.collateral_auction_house.auctions_started()
        assert auctions_before == auctions_after

    @classmethod
    def teardown_class(cls):
        w3 = web3()
        print("tearing down TestAuctionKeeperLiquidate")
        cls.eliminate_queued_debt(w3, geb(w3), keeper_address(w3))

    @classmethod
    def eliminate_queued_debt(cls, web3, geb, keeper_address):
        if geb.safe_engine.debt_balance(geb.accounting_engine.address) == Rad(0):
            return

        # given the existence of queued debt
        c = geb.collaterals['ETH-A']
        auction_id = c.collateral_auction_house.auctions_started()
        last_liquidation = geb.liquidation_engine.past_liquidations(10)[0]

        # when a bid covers the SAFE debt
        auction = c.collateral_auction_house.bids(auction_id)
        reserve_system_coin(geb, c, keeper_address, Wad(auction.amount_to_raise) + Wad(1))
        c.collateral_auction_house.approve(c.collateral_auction_house.safe_engine(), approval_function=approve_safe_modification_directly(from_address=keeper_address))
        c.approve(keeper_address)
        if isinstance(c.collateral_auction_house, EnglishCollateralAuctionHouse):
            assert c.collateral_auction_house.increase_bid_size(auction_id, auction.amount_to_sell,
                                                                auction.amount_to_raise).transact(from_address=keeper_address)
            time_travel_by(web3, c.collateral_auction_house.bid_duration() + 1)
            assert c.collateral_auction_house.settle_auction(auction_id).transact()
        elif isinstance(c.collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            assert c.collateral_auction_house.buy_collateral(auction_id, Wad(auction.amount_to_raise) + Wad(1)).transact(from_address=keeper_address)

        # when a bid covers the vow debt
        assert geb.accounting_engine.debt_queue_of(last_liquidation.block_time(web3)) > Rad(0)
        assert geb.accounting_engine.pop_debt_from_queue(last_liquidation.block_time(web3)).transact(from_address=keeper_address)
        assert geb.accounting_engine.settle_debt(geb.safe_engine.debt_balance(geb.accounting_engine.address)).transact()

        # then ensure queued debt has been auctioned off
        assert geb.safe_engine.debt_balance(geb.accounting_engine.address) == Rad(0)
