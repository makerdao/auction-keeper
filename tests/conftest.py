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
import os
import pytest

from web3 import Web3, HTTPProvider

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from mock import MagicMock
from pymaker import Address
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Ilk, Urn
from pymaker.feed import DSValue
from pymaker.keys import register_keys
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSEthToken, DSToken
from typing import Optional


@pytest.fixture(scope="session")
def web3():
    # These details are specific to the MCD testchain used for pymaker unit tests.
    web3 = Web3(HTTPProvider("http://0.0.0.0:8545"))
    web3.eth.defaultAccount = "0x50FF810797f75f6bfbf2227442e0c961a8562F4C"
    register_keys(web3,
                  ["key_file=lib/pymaker/tests/config/keys/UnlimitedChain/key1.json,pass_file=/dev/null",
                   "key_file=lib/pymaker/tests/config/keys/UnlimitedChain/key2.json,pass_file=/dev/null",
                   "key_file=lib/pymaker/tests/config/keys/UnlimitedChain/key3.json,pass_file=/dev/null",
                   "key_file=lib/pymaker/tests/config/keys/UnlimitedChain/key4.json,pass_file=/dev/null",
                   "key_file=lib/pymaker/tests/config/keys/UnlimitedChain/key.json,pass_file=/dev/null"])

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


def wrap_eth(mcd: DssDeployment, address: Address, amount: Wad):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(address, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    collateral = mcd.collaterals['ETH-A']
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
def mcd(web3):
    return DssDeployment.from_network(web3=web3, network="testnet")


@pytest.fixture(scope="session")
def c(mcd):
    return mcd.collaterals['ETH-B']


def get_collateral_price(collateral: Collateral):
    assert isinstance(collateral, Collateral)
    return Wad(Web3.toInt(collateral.pip.read()))


def set_collateral_price(mcd: DssDeployment, collateral: Collateral, price: Wad):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(price, Wad)
    assert price > Wad(0)

    pip = collateral.pip
    assert isinstance(pip, DSValue)

    print(f"Changing price of {collateral.ilk.name} to {price}")
    assert pip.poke_with_int(price.value).transact(from_address=pip.get_owner())
    assert mcd.spotter.poke(ilk=collateral.ilk).transact(from_address=pip.get_owner())

    assert get_collateral_price(collateral) == price


def max_dart(mcd: DssDeployment, collateral: Collateral, our_address: Address) -> Wad:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(our_address, Address)

    urn = mcd.vat.urn(collateral.ilk, our_address)
    ilk = mcd.vat.ilk(collateral.ilk.name)

    # change in art = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    dart = urn.ink * ilk.spot - Wad(Ray(urn.art) * ilk.rate)

    # change in debt must also take the rate into account
    dart = dart * Wad(Ray.from_number(1) / ilk.rate)

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(urn.art) + Rad(dart)) >= ilk.line:
        print("max_dart is avoiding collateral debt ceiling")
        dart = Wad(ilk.line - Rad(urn.art))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = mcd.vat.debt() + Rad(ilk.rate * dart)
    line = Rad(ilk.line)
    if (debt + Rad(dart)) >= line:
        print("max_dart is avoiding total debt ceiling")
        dart = Wad(debt - Rad(urn.art))

    assert dart > Wad(0)
    return dart


def reserve_dai(mcd: DssDeployment, c: Collateral, usr: Address, amount: Wad, extra_collateral=Wad.from_number(1)):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(usr, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    # Determine how much collateral is needed
    ilk = mcd.vat.ilk(c.ilk.name)
    rate = ilk.rate  # Ray
    spot = ilk.spot  # Ray
    assert rate >= Ray.from_number(1)
    collateral_required = Wad((Ray(amount) / spot) * rate) * extra_collateral + Wad(1)
    print(f'collateral_required for {str(amount)} dai is {str(collateral_required)}')

    wrap_eth(mcd, usr, collateral_required)
    c.approve(usr)
    assert c.adapter.join(usr, collateral_required).transact(from_address=usr)
    simulate_frob(mcd, c, usr, collateral_required, amount)
    assert mcd.vat.frob(c.ilk, usr, collateral_required, amount).transact(from_address=usr)
    assert mcd.vat.urn(c.ilk, usr).art >= Wad(amount)


def simulate_frob(mcd: DssDeployment, collateral: Collateral, address: Address, dink: Wad, dart: Wad):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    assert isinstance(dink, Wad)
    assert isinstance(dart, Wad)

    urn = mcd.vat.urn(collateral.ilk, address)
    ilk = mcd.vat.ilk(collateral.ilk.name)

    # print(f"[urn.ink={urn.ink}, urn.art={urn.art}] [ilk.rate={ilk.rate} ilk.art={ilk.art}, ilk.line={ilk.line}]")
    # print(f"[dink={dink}, dart={dart}] [debt={str(mcd.vat.debt())} line={str(mcd.vat.line())}]")
    ink = urn.ink + dink
    art = urn.art + dart
    ilk_art = ilk.art + dart
    rate = ilk.rate

    debt = mcd.vat.debt() + Rad(rate * dart)

    # stablecoin debt does not increase
    cool = dart <= Wad(0)
    # collateral balance does not decrease
    firm = dink >= Wad(0)

    # CDP remains under both collateral and total debt ceilings
    under_collateral_debt_ceiling = Rad(ilk_art * rate) <= ilk.line
    if not under_collateral_debt_ceiling:
        print(f"CDP would exceed collateral debt ceiling of {ilk.line}")
    under_total_debt_ceiling = debt < mcd.vat.line()
    if not under_total_debt_ceiling:
        print(f"CDP would exceed total debt ceiling of {mcd.vat.line()}")
    calm = under_collateral_debt_ceiling and under_total_debt_ceiling

    safe = (urn.art * rate) <= ink * ilk.spot

    assert calm or cool
    assert (cool and firm) or safe

    assert Rad(ilk_art * rate) >= ilk.dust or (art == Wad(0))
    assert rate != Ray(0)
    assert mcd.vat.live()


def is_cdp_safe(ilk: Ilk, urn: Urn) -> bool:
    assert isinstance(urn, Urn)
    assert urn.art is not None
    assert ilk.rate is not None
    assert urn.ink is not None
    assert ilk.spot is not None

    #print(f'art={urn.art} * rate={ilk.rate} <=? ink={urn.ink} * spot={ilk.spot}')
    return (Ray(urn.art) * ilk.rate) <= Ray(urn.ink) * ilk.spot


def create_unsafe_cdp(mcd: DssDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address,
                      draw_dai=True) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure CDP isn't already unsafe (if so, this shouldn't be called)
    urn = mcd.vat.urn(c.ilk, gal_address)
    assert is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn)

    # Add collateral to gal CDP if necessary
    c.approve(gal_address)
    dink = collateral_amount - urn.ink
    if dink > Wad(0):
        balance = c.gem.balance_of(gal_address)
        if balance < dink:
            wrap_eth(mcd, gal_address, dink - balance)
            assert c.adapter.join(gal_address, dink - balance).transact(from_address=gal_address)
        simulate_frob(mcd, c, gal_address, dink, Wad(0))
        assert mcd.vat.frob(c.ilk, gal_address, dink, Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    dart = max_dart(mcd, c, gal_address) - Wad(1)
    simulate_frob(mcd, c, gal_address, Wad(0), dart)
    assert mcd.vat.frob(c.ilk, gal_address, Wad(0), dart).transact(from_address=gal_address)

    # Draw our Dai, simulating the usual behavior
    urn = mcd.vat.urn(c.ilk, gal_address)
    if draw_dai and urn.art > Wad(0):
        mcd.approve_dai(gal_address)
        assert mcd.dai_adapter.exit(gal_address, urn.art).transact(from_address=gal_address)
        print(f"Exited {urn.art} Dai from urn")

    # Manipulate price to make gal CDP underwater
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    set_collateral_price(mcd, c, to_price)

    # Ensure the CDP is unsafe
    assert not is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn)
    return urn


def create_cdp_with_surplus(mcd: DssDeployment, c: Collateral, gal_address: Address) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure there is no debt which a previous test failed to clean up
    assert mcd.vat.sin(mcd.vow.address) == Rad(0)

    ink = Wad.from_number(10)
    art = Wad.from_number(500)
    wrap_eth(mcd, gal_address, ink)
    c.approve(gal_address)
    assert c.adapter.join(gal_address, ink).transact(
        from_address=gal_address)
    simulate_frob(mcd, c, gal_address, ink, art)
    assert mcd.vat.frob(c.ilk, gal_address, dink=ink, dart=art).transact(
        from_address=gal_address)
    assert mcd.jug.drip(c.ilk).transact(from_address=gal_address)
    # total surplus > total debt + surplus auction lot size + surplus buffer
    print(f"dai(vow)={str(mcd.vat.dai(mcd.vow.address))} >? sin(vow)={str(mcd.vat.sin(mcd.vow.address))} " 
          f"+ vow.bump={str(mcd.vow.bump())} + vow.hump={str(mcd.vow.hump())}")
    assert mcd.vat.dai(mcd.vow.address) > mcd.vat.sin(mcd.vow.address) + mcd.vow.bump() + mcd.vow.hump()
    return mcd.vat.urn(c.ilk, gal_address)


def bite(mcd: DssDeployment, c: Collateral, unsafe_cdp: Urn) -> int:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(unsafe_cdp, Urn)

    assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()
    bites = mcd.cat.past_bite(1)
    assert len(bites) == 1
    return c.flipper.kicks()


def flog_and_heal(web3: Web3, mcd: DssDeployment, past_blocks=8, kiss=True, require_heal=True):
    # Raise debt from the queue (note that vow.wait is 0 on our testchain)
    bites = mcd.cat.past_bite(past_blocks)
    for bite in bites:
        era_bite = bite.era(web3)
        sin = mcd.vow.sin_of(era_bite)
        if sin > Rad(0):
            print(f'flogging era={era_bite} from block={bite.raw["blockNumber"]} '
                  f'with sin={str(mcd.vow.sin_of(era_bite))}')
            assert mcd.vow.flog(era_bite).transact()
            assert mcd.vow.sin_of(era_bite) == Rad(0)

    # Ensure there is no on-auction debt which a previous test failed to clean up
    if kiss and mcd.vow.ash() > Rad.from_number(0):
        assert mcd.vow.kiss(mcd.vow.ash()).transact()
        assert mcd.vow.ash() == Rad.from_number(0)

    # Cancel out surplus and debt
    joy = mcd.vat.dai(mcd.vow.address)
    woe = mcd.vow.woe()
    if require_heal:
        assert joy <= woe
    if joy <= woe:
        assert mcd.vow.heal(joy).transact()


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
