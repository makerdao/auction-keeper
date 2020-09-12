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
from pyflex.dss import Collateral, Ilk, Urn
from pyflex.feed import DSValue
from pyflex.gas import NodeAwareGasPrice
from pyflex.keys import register_keys
from pyflex.model import Token
from pyflex.numeric import Wad, Ray, Rad
from pyflex.token import DSEthToken, DSToken


@pytest.fixture(scope="session")
def web3():
    # These details are specific to the MCD testchain used for pyflex unit tests.
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
def gal_address(web3):
    return Address(web3.eth.accounts[3])


def wrap_eth(geb: GfDeployment, address: Address, amount: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    collateral = geb.collaterals['ETH-A']
    assert isinstance(collateral.gem, DSEthToken)
    assert collateral.gem.deposit(amount).transact(from_address=address)


def mint_mkr(mkr: DSToken, recipient_address: Address, amount: Wad):
    assert isinstance(mkr, DSToken)
    assert isinstance(recipient_address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    deployment_address = Address("0x00a329c0648769A73afAc7F9381E08FB43dBEA72")
    assert mkr.mint(amount).transact(from_address=deployment_address)
    assert mkr.balance_of(deployment_address) > Wad(0)
    assert mkr.approve(recipient_address).transact(from_address=deployment_address)
    assert mkr.transfer(recipient_address, amount).transact(from_address=deployment_address)


@pytest.fixture(scope="session")
def geb(web3):
    return GfDeployment.from_node(web3=web3)


@pytest.fixture(scope="session")
def c(geb):
    return geb.collaterals['ETH-B']


def get_collateral_price(collateral: Collateral):
    assert isinstance(collateral, Collateral)
    return Wad(Web3.toInt(collateral.pip.read()))


def set_collateral_price(geb: GfDeployment, collateral: Collateral, price: Wad):
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    pip = collateral.pip
    assert isinstance(pip, DSValue)

    print(f"Changing price of {collateral.ilk.name} to {price}")
    assert pip.poke_with_int(price.value).transact(from_address=pip.get_owner())
    assert geb.spotter.poke(ilk=collateral.ilk).transact(from_address=pip.get_owner())

    assert get_collateral_price(collateral) == price


def max_dart(geb: GfDeployment, collateral: Collateral, our_address: Address) -> Wad:
    assert isinstance(geb, GfDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    safe = geb.safe_engine.safe(collateral.ilk, our_address)
    ilk = geb.safe_engine.ilk(collateral.ilk.name)

    # change in art = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    dart = safe.ink * ilk.spot - Wad(Ray(safe.art) * ilk.rate)

    # change in debt must also take the rate into account
    dart = Wad(Ray(dart) / ilk.rate)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(safe.art) + Rad(dart)) >= ilk.line:
        print("max_dart is avoiding collateral debt ceiling")
        dart = Wad(ilk.line - Rad(safe.art))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = geb.safe_engine.debt() + Rad(ilk.rate * dart)
    line = Rad(geb.safe_engine.line())
    if (debt + Rad(dart)) >= line:
        print(f"debt {debt} + dart {dart} >= {line}; max_dart is avoiding total debt ceiling")
        dart = Wad(debt - Rad(safe.art))

    # ensure we've met the dust cutoff
    if Rad(safe.art + dart) < ilk.dust:
        print(f"max_dart is being bumped from {safe.art + dart} to {ilk.dust} to reach dust cutoff")
        dart = Wad(ilk.dust)

    return dart


def reserve_system_coin(geb: GfDeployment, c: Collateral, usr: Address, amount: Wad, extra_collateral=Wad.from_number(1)):
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(usr, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    # Determine how much collateral is needed
    ilk = geb.safe_engine.ilk(c.ilk.name)
    rate = ilk.rate  # Ray
    spot = ilk.spot  # Ray
    assert rate >= Ray.from_number(1)
    collateral_required = Wad((Ray(amount) / spot) * rate) * extra_collateral + Wad(1)
    print(f'collateral_required for {str(amount)} system_coin is {str(collateral_required)}')

    wrap_eth(geb, usr, collateral_required)
    c.approve(usr)
    assert c.adapter.join(usr, collateral_required).transact(from_address=usr)
    assert geb.safe_engine.frob(c.ilk, usr, collateral_required, amount).transact(from_address=usr)
    assert geb.safe_engine.safe(c.ilk, usr).art >= Wad(amount)


def purchase_system_coin(amount: Wad, recipient: Address):
    assert isinstance(amount, Wad)
    assert isinstance(recipient, Address)

    m = geb(web3())
    seller = gal_address(web3())
    reserve_system_coin(m, m.collaterals['ETH-C'], seller, amount)
    m.approve_system_coin(seller)
    m.approve_system_coin(recipient)
    assert m.system_coin_adapter.exit(seller, amount).transact(from_address=seller)
    assert m.system_coin.transfer_from(seller, recipient, amount).transact(from_address=seller)


def is_cdp_safe(ilk: Ilk, safe: Urn) -> bool:
    assert isinstance(safe, Urn)
    assert safe.art is not None
    assert ilk.rate is not None
    assert safe.ink is not None
    assert ilk.spot is not None

    #print(f'art={safe.art} * rate={ilk.rate} <=? ink={safe.ink} * spot={ilk.spot}')
    return (Ray(safe.generated_debt) * collateral_type.accumulated_rate) <= Ray(safe.safe_collateral) * collateral_type.safety_price

def create_risky_cdp(geb: GfDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address,
                     draw_system_coin=True) -> Urn:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure vault isn't already unsafe (if so, this shouldn't be called)
    safe = geb.safe_engine.safe(c.collateral_type, gal_address)
    assert is_cdp_safe(geb.safe_engine.collateral_type(c.collateral_type.name), safe)

    # Add collateral to gal vault if necessary
    c.approve(gal_address)
    token = Token(c.ilk.name, c.gem.address, c.adapter.dec())
    print(f"collateral_amount={collateral_amount} ink={safe.ink}")
    dink = collateral_amount - safe.ink
    if dink > Wad(0):
        safe_engine_balance = geb.safe_engine.gem(c.ilk, gal_address)
        balance = token.normalize_amount(c.gem.balance_of(gal_address))
        print(f"before join: dink={dink} safe_engine_balance={safe_engine_balance} balance={balance} safe_engine_gap={dink - safe_engine_balance}")
        if safe_engine_balance < dink:
            safe_engine_gap = dink - safe_engine_balance
            if balance < safe_engine_gap:
                if c.ilk.name.startswith("ETH"):
                    wrap_eth(geb, gal_address, safe_engine_gap)
                else:
                    raise RuntimeError("Insufficient collateral balance")
            amount_to_join = token.unnormalize_amount(safe_engine_gap)
            if amount_to_join == Wad(0):  # handle dusty balances with non-18-decimal tokens
                amount_to_join += token.unnormalize_amount(token.min_amount)
            assert c.adapter.join(gal_address, amount_to_join).transact(from_address=gal_address)
        safe_engine_balance = geb.safe_engine.gem(c.ilk, gal_address)
        print(f"after join: dink={dink} safe_engine_balance={safe_engine_balance} balance={balance} safe_engine_gap={dink - safe_engine_balance}")
        assert safe_engine_balance >= dink
        assert geb.safe_engine.frob(c.ilk, gal_address, dink, Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    dart = max_dart(geb, c, gal_address) - Wad(1)
    if dart > Wad(0):
        print(f"Attempting to frob with dart={dart}")
        assert geb.safe_engine.frob(c.ilk, gal_address, Wad(0), dart).transact(from_address=gal_address)

    # Draw our Dai, simulating the usual behavior
    safe = geb.safe_engine.safe(c.collateral_type, gal_address)
    if draw_system_coin and safe.generated_debt > Wad(0):
        geb.approve_system_coin(gal_address)
        assert geb.system_coin_adapter.exit(gal_address, safe.generated_debt).transact(from_address=gal_address)
        print(f"Exited {safe.generated_debt} System coin from safe")


def create_unsafe_cdp(geb: GfDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address,
                      draw_system_coin=True) -> Safe:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    create_risky_cdp(geb, c, collateral_amount, gal_address, draw_system_coin)
    safe = geb.safe_engine.urn(c.collateral_type, gal_address)

    # Manipulate price to make gal CDP underwater
    to_price = Wad(c.osm.read_as_int()) - Wad.from_number(1)
    set_collateral_price(geb, c, to_price)

    # Ensure the CDP is unsafe
    assert not is_cdp_safe(geb.safe_engine.collateral_type(c.collateral_type.name), safe)
    return safe

def create_cdp_with_surplus(geb: GfDeployment, c: Collateral, gal_address: Address) -> Safe:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure there is no debt which a previous test failed to clean up
    assert geb.safe_engine.debt_balance(geb.accounting_engine.address) == Rad(0)

    safe_collateral = Wad.from_number(1)
    safe_debt = Wad.from_number(50)
    wrap_eth(geb, gal_address, safe_collateral)
    c.approve(gal_address)
    assert c.adapter.join(gal_address, safe_collateral).transact(
        from_address=gal_address)
    assert geb.safe_engine.modify_safe_collateralization(c.collateral_type, gal_address, delta_collateral=safe_collateral,
                                                         delta_debt=safe_debt).transact(from_address=gal_address)
    assert geb.tax_collector.tax_single(c.collateral_type).transact(from_address=gal_address)
    # total surplus > total debt + surplus auction lot size + surplus buffer
    print(f"system_coin(accounting_engine)={str(geb.safe_engine.system_coin(geb.accounting_engine.address))} >? debt_balance(accounting_engine)={str(geb.safe_engine.debt_balance(geb.accounting_engine.address))} " 
          f"+ accounting_engine.surplus_auction_amount_to_sell={str(geb.accounting_engine.surplus_auction_amount_to_sell())} + accounting_engine.surplus_buffer={str(geb.accounting_engine.surplus_buffer())}")
    assert geb.safe_engine.system_coin(geb.accounting_engine.address) > mcd.safe_engine.sin(geb.accounting_engine.address) + geb.accounting_engine.bump() + geb.accounting_engine.hump()
    return geb.safe_engine.urn(c.ilk, gal_address)


def bite(geb: GfDeployment, c: Collateral, unsafe_cdp: Urn) -> int:
    assert isinstance(geb, GfDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(unsafe_cdp, Urn)

    assert geb.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()
    bites = geb.cat.past_bites(1)
    assert len(bites) == 1
    return c.flipper.kicks()


def pop_debt_and_settle_debt(web3: Web3, geb: GfDeployment, past_blocks=8, cancel_auctioned_debt=True, require_settle_debt=True):
    # Raise debt from the queue (note that accounting_engine.wait is 0 on our testchain)
    liquidations = geb.liquidation_engine.past_liquidations(past_blocks)
    for liquidation in liquidations:
        era_liquidation = bite.era(web3)
        debt_queue = geb.accounting_engine.debt_queue_of(era_liquidation)
        if debt_queue > Rad(0):
            print(f'popping debt era={era_liquidation} from block={liquidation.raw["blockNumber"]} '
                  f'with debt_queue={str(geb.accounting_engine.debt_queue_of(era_liquidation))}')
            assert geb.accounting_engine.pop_debt_from_queue(era_liquidation).transact()
            assert geb.accounting_engine.debt_queue_of(era_liquidation) == Rad(0)

    # Ensure there is no on-auction debt which a previous test failed to clean up
    if cancle_auctioned_debtt and geb.accounting_engine.total_on_auction_debt() > Rad.from_number(0):
        assert geb.accounting_engine.cancel_auctioned_debt_with_surplus(geb.accounting_engine.total_on_auction_debt()).transact()
        assert geb.accounting_engine.total_on_auction_debt() == Rad.from_number(0)

    # Cancel out surplus and debt
    joy = geb.safe_engine.system_coin(geb.accounting_engine.address)
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
