# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel
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
import pytest

from mock import MagicMock
from typing import Optional
from web3 import Web3

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from pyflex import Address, web3_via_http
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, CollateralType, SAFE
from pyflex.feed import DSValue
from pyflex.gas import NodeAwareGasPrice
from pyflex.keys import register_keys
from pyflex.model import Token
from pyflex.numeric import Wad, Ray, Rad
from pyflex.token import DSEthToken, DSToken


@pytest.fixture(scope="session")
def web3():
    # These details are specific to the GEB testchain used for pyflex unit tests.
    web3 = web3_via_http("http://0.0.0.0:8545", 3, 100)
    web3.eth.defaultAccount = "0x50FF810797f75f6bfbf2227442e0c961a8562F4C"
    register_keys(web3,
                  ["key_file=lib/pyflex/tests/config/keys/UnlimitedChain/key1.json,pass_file=/dev/null",
                   "key_file=lib/pyflex/tests/config/keys/UnlimitedChain/key2.json,pass_file=/dev/null",
                   "key_file=lib/pyflex/tests/config/keys/UnlimitedChain/key3.json,pass_file=/dev/null",
                   "key_file=lib/pyflex/tests/config/keys/UnlimitedChain/key4.json,pass_file=/dev/null",
                   "key_file=lib/pyflex/tests/config/keys/UnlimitedChain/key.json,pass_file=/dev/null"])

    # reduce logspew
    logging.getLogger("web3").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.INFO)

    return web3


@pytest.fixture(scope="session")
def our_address(web3):
    return Address(web3.eth.accounts[0])


@pytest.fixture(scope="session")
def keeper_address(web3):
    return Address(web3.eth.accounts[1])


@pytest.fixture(scope="session")
def other_address(web3):
    return Address(web3.eth.accounts[2])


@pytest.fixture(scope="session")
def auction_income_recipient_address(web3):
    return Address(web3.eth.accounts[3])


def wrap_eth(geb: GfDeployment, address: Address, amount: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    collateral = geb.collaterals['ETH-A']
    assert isinstance(collateral.collateral, DSEthToken)
    assert collateral.collateral.deposit(amount).transact(from_address=address)


def mint_prot(prot: DSToken, recipient_address: Address, amount: Wad):
    assert isinstance(prot, DSToken)
    assert isinstance(recipient_address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    deployment_address = Address("0x00a329c0648769A73afAc7F9381E08FB43dBEA72")
    assert prot.mint(amount).transact(from_address=deployment_address)
    assert prot.balance_of(deployment_address) > Wad(0)
    assert prot.approve(recipient_address).transact(from_address=deployment_address)
    assert prot.transfer(recipient_address, amount).transact(from_address=deployment_address)


@pytest.fixture(scope="session")
def geb(web3):
    return GfDeployment.from_node(web3=web3)


@pytest.fixture(scope="session")
def c(geb):
    return geb.collaterals['ETH-B']


def get_collateral_price(collateral: Collateral):
    assert isinstance(collateral, Collateral)
    return Wad(Web3.toInt(collateral.osm.read()))


def set_collateral_price(geb: GfDeployment, collateral: Collateral, price: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    osm = collateral.osm
    assert isinstance(osm, DSValue)

    print(f"Changing price of {collateral.collateral_type.name} to {price}")
    assert osm.update_result(price.value).transact(from_address=osm.get_owner())
    assert geb.oracle_relayer.update_collateral_price(collateral_type=collateral.collateral_type).transact(from_address=osm.get_owner())

    assert get_collateral_price(collateral) == price


def max_delta_debt(geb: GfDeployment, collateral: Collateral, our_address: Address) -> Wad:
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    safe = geb.safe_engine.safe(collateral.collateral_type, our_address)
    collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)

    # change in debt = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    delta_debt = safe.locked_collateral * collateral_type.safety_price - Wad(Ray(safe.generated_debt) * collateral_type.accumulated_rate)

    # change in debt must also take the rate into account
    delta_debt = Wad(Ray(delta_debt) / collateral_type.accumulated_rate)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(safe.generated_debt) + Rad(delta_debt)) >= collateral_type.debt_ceiling:
        print("max_delta_debt is avoiding collateral debt ceiling")
        delta_debt = Wad(collateral_type.delta_ceiling - Rad(safe.generated_debt))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = geb.safe_engine.global_debt() + Rad(collateral_type.accumulated_rate * delta_debt)
    debt_ceiling = Rad(geb.safe_engine.global_debt_ceiling())
    if (debt + Rad(delta_debt)) >= debt_ceiling:
        print(f"debt {debt} + delta_debt {delta_debt} >= {debt_ceiling}; max_delta_debt is avoiding total debt ceiling")
        delta_debt = Wad(debt - Rad(safe.generated_debt))

    # ensure we've met the debt_floor cutoff
    if Rad(safe.generated_debt + delta_debt) < collateral_type.debt_floor:
        print(f"max_delta_debt is being bumped from {safe.generated_debt + delta_debt} to {collateral_type.debt_floor} to reach debt_floor cutoff")
        delta_debt = Wad(collateral_type.debt_floor)

    return delta_debt

def reserve_system_coin(geb: GfDeployment, c: Collateral, usr: Address, amount: Wad, extra_collateral=Wad.from_number(1)):
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(usr, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    # Determine how much collateral is needed
    collateral_type = geb.safe_engine.collateral_type(c.collateral_type.name)
    accumulated_rate = collateral_type.accumulated_rate  # Ray
    safety_price = collateral_type.safety_price  # Ray
    assert accumulated_rate >= Ray.from_number(1)
    collateral_required = Wad((Ray(amount) / safety_price) * accumulated_rate) * extra_collateral + Wad(1)
    print(f'collateral_required for {str(amount)} system_coin is {str(collateral_required)}')

    wrap_eth(geb, usr, collateral_required)
    c.approve(usr)
    assert c.adapter.join(usr, collateral_required).transact(from_address=usr)
    assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, usr, collateral_required, amount).transact(from_address=usr)
    assert geb.safe_engine.safe(c.collateral_type, usr).generated_debt >= Wad(amount)


def purchase_system_coin(amount: Wad, recipient: Address):
    assert isinstance(amount, Wad)
    assert isinstance(recipient, Address)

    m = geb(web3())
    seller = auction_income_recipient_address(web3())
    reserve_system_coin(m, m.collaterals['ETH-C'], seller, amount)
    m.approve_system_coin(seller)
    m.approve_system_coin(recipient)
    assert m.system_coin_adapter.exit(seller, amount).transact(from_address=seller)
    assert m.system_coin.transfer_from(seller, recipient, amount).transact(from_address=seller)


def is_safe_safe(collateral_type: CollateralType, safe: SAFE) -> bool:
    assert isinstance(safe, SAFE)
    assert safe.generated_debt is not None
    assert collateral_type.accumulated_rate is not None
    assert safe.locked_collateral is not None
    assert collateral_type.safety_price is not None

    #print(f'art={safe.generated_debt} * rate={collateral_type.rate} <=? ink={safe.locked_collateral} * spot={collateral_type.spot}')
    return (Ray(safe.generated_debt) * collateral_type.accumulated_rate) <= Ray(safe.locked_collateral) * collateral_type.safety_price

def create_risky_safe(geb: GfDeployment, c: Collateral, collateral_amount: Wad, auction_income_recipient_address: Address,
                     draw_system_coin=True) -> SAFE:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(auction_income_recipient_address, Address)

    # Ensure vault isn't already unsafe (if so, this shouldn't be called)
    safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
    assert is_safe_safe(geb.safe_engine.collateral_type(c.collateral_type.name), safe)

    # Add collateral to gal vault if necessary
    c.approve(auction_income_recipient_address)
    token = Token(c.collateral_type.name, c.collateral.address, c.adapter.decimals())
    print(f"collateral_amount={collateral_amount} ink={safe.locked_collateral}")
    delta_collateral = collateral_amount - safe.locked_collateral
    if delta_collateral > Wad(0):
        safe_engine_balance = geb.safe_engine.token_collateral(c.collateral_type, auction_income_recipient_address)
        balance = token.normalize_amount(c.collateral.balance_of(auction_income_recipient_address))
        print(f"before join: delta_collateral={delta_collateral} safe_engine_balance={safe_engine_balance} balance={balance} safe_engine_gap={delta_collateral - safe_engine_balance}")
        if safe_engine_balance < delta_collateral:
            safe_engine_gap = delta_collateral - safe_engine_balance
            if balance < safe_engine_gap:
                if c.collateral_type.name.startswith("ETH"):
                    wrap_eth(geb, auction_income_recipient_address, safe_engine_gap)
                else:
                    raise RuntimeError("Insufficient collateral balance")
            amount_to_join = token.unnormalize_amount(safe_engine_gap)
            if amount_to_join == Wad(0):  # handle dusty balances with non-18-decimal tokens
                amount_to_join += token.unnormalize_amount(token.min_amount)
            assert c.adapter.join(auction_income_recipient_address, amount_to_join).transact(from_address=auction_income_recipient_address)
        safe_engine_balance = geb.safe_engine.token_collateral(c.collateral_type, auction_income_recipient_address)
        print(f"after join: delta_collateral={delta_collateral} safe_engine_balance={safe_engine_balance} balance={balance} safe_engine_gap={delta_collateral - safe_engine_balance}")
        assert safe_engine_balance >= delta_collateral
        assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, auction_income_recipient_address, delta_collateral, Wad(0)).transact(from_address=auction_income_recipient_address)

    # Put gal CDP at max possible debt
    delta_debt = max_delta_debt(geb, c, auction_income_recipient_address) - Wad(1)
    if delta_debt > Wad(0):
        print(f"Attempting to modify safe collateralization with delta_debt={delta_debt}")
        assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, auction_income_recipient_address, Wad(0), delta_debt).transact(from_address=auction_income_recipient_address)

    # Draw our Dai, simulating the usual behavior
    safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)
    if draw_system_coin and safe.generated_debt > Wad(0):
        geb.approve_system_coin(auction_income_recipient_address)
        assert geb.system_coin_adapter.exit(auction_income_recipient_address, safe.generated_debt).transact(from_address=auction_income_recipient_address)
        print(f"Exited {safe.generated_debt} System coin from safe")


def create_unsafe_safe(geb: GfDeployment, c: Collateral, collateral_amount: Wad, auction_income_recipient_address: Address,
                      draw_system_coin=True) -> SAFE:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(auction_income_recipient_address, Address)

    create_risky_safe(geb, c, collateral_amount, auction_income_recipient_address, draw_system_coin)
    safe = geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)

    # Manipulate price to make gal CDP underwater
    to_price = Wad(c.osm.read()) - Wad.from_number(1)
    set_collateral_price(geb, c, to_price)

    # Ensure the SAFE is unsafe
    assert not is_safe_safe(geb.safe_engine.collateral_type(c.collateral_type.name), safe)
    return safe

def create_safe_with_surplus(geb: GfDeployment, c: Collateral, auction_income_recipient_address: Address) -> SAFE:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(auction_income_recipient_address, Address)

    # Ensure there is no debt which a previous test failed to clean up
    assert geb.safe_engine.debt_balance(geb.accounting_engine.address) == Rad(0)

    safe_collateral = Wad.from_number(1)
    safe_debt = Wad.from_number(50)
    wrap_eth(geb, auction_income_recipient_address, safe_collateral)
    c.approve(auction_income_recipient_address)
    assert c.adapter.join(auction_income_recipient_address, safe_collateral).transact(
        from_address=auction_income_recipient_address)
    assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, auction_income_recipient_address, delta_collateral=safe_collateral,
                                                         delta_debt=safe_debt).transact(from_address=auction_income_recipient_address)
    assert geb.tax_collector.tax_single(c.collateral_type).transact(from_address=auction_income_recipient_address)
    # total surplus > total debt + surplus auction lot size + surplus buffer
    print(f"system_coin(accounting_engine)={str(geb.safe_engine.coin_balance(geb.accounting_engine.address))} >? debt_balance(accounting_engine)={str(geb.safe_engine.debt_balance(geb.accounting_engine.address))} " 
          f"+ accounting_engine.surplus_auction_amount_to_sell={str(geb.accounting_engine.surplus_auction_amount_to_sell())} + accounting_engine.surplus_buffer={str(geb.accounting_engine.surplus_buffer())}")
    assert geb.safe_engine.coin_balance(geb.accounting_engine.address) > mcd.safe_engine.sin(geb.accounting_engine.address) + geb.accounting_engine.bump() + geb.accounting_engine.hump()
    return geb.safe_engine.safe(c.collateral_type, auction_income_recipient_address)


def liquidate(geb: GfDeployment, c: Collateral, unsafe_safe: SAFE) -> int:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(unsafe_safe, SAFE)

    assert geb.liquidation_engine.liquidate_safe(unsafe_safe.collateral_type, unsafe_safe).transact()
    liquidations = geb.liquidation_engine.past_liquidations(1)
    assert len(liquidations) == 1
    return c.collateral_auction_house.auctions_started()

def pop_debt_and_settle_debt(web3: Web3, geb: GfDeployment, past_blocks=8, cancel_auctioned_debt=True, require_settle_debt=True):
    # Raise debt from the queue (note that accounting_engine.wait is 0 on our testchain)
    liquidations = geb.liquidation_engine.past_liquidations(past_blocks)
    for liquidation in liquidations:
        era_liquidation = liquidation.era(web3)
        debt_queue = geb.accounting_engine.debt_queue_of(era_liquidation)
        if debt_queue > Rad(0):
            print(f'popping debt era={era_liquidation} from block={liquidation.raw["blockNumber"]} '
                  f'with debt_queue={str(geb.accounting_engine.debt_queue_of(era_liquidation))}')
            assert geb.accounting_engine.pop_debt_from_queue(era_liquidation).transact()
            assert geb.accounting_engine.debt_queue_of(era_liquidation) == Rad(0)

    # Ensure there is no on-auction debt which a previous test failed to clean up
    if cancel_auctioned_debt and geb.accounting_engine.total_on_auction_debt() > Rad.from_number(0):
        assert geb.accounting_engine.cancel_auctioned_debt_with_surplus(geb.accounting_engine.total_on_auction_debt()).transact()
        assert geb.accounting_engine.total_on_auction_debt() == Rad.from_number(0)

    # Cancel out surplus and debt
    joy = geb.safe_engine.coin_balance(geb.accounting_engine.address)
    unqueued_unauctioned_debt = geb.accounting_engine.unqueued_unauctioned_debt()
    if require_settle_debt:
        assert joy <= unqueued_unauctioned_debt
    if joy <= unqueued_unauctioned_debt:
        assert geb.accounting_engine.settle_debt(joy).transact()


def models(keeper: AuctionKeeper, id: int):
    assert (isinstance(keeper, AuctionKeeper))
    assert (isinstance(id, int))

    model = MagicMock()
    model.get_stance = MagicMock(return_value=None)
    model.id = id
    model_factory = keeper.auctions.model_factory
    model_factory.create_model = MagicMock(return_value=model)
    return (model, model_factory)


def simulate_model_output(model: object, price: Wad, gas_price: Optional[int] = None):
    assert (isinstance(price, Wad))
    assert (isinstance(gas_price, int)) or gas_price is None
    model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))


def get_node_gas_price(web3: Web3):
    class DummyGasStrategy(NodeAwareGasPrice):
        def get_gas_price(self, time_elapsed: int) -> Optional[int]:
            return self.get_node_gas_price()

    assert isinstance(web3, Web3)
    dummy = DummyGasStrategy(web3)
    return dummy.get_node_gas_price()
