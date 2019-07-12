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

from web3 import Web3, HTTPProvider

from auction_keeper.main import AuctionKeeper
from pymaker import Address
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Ilk, Urn
from pymaker.feed import DSValue
from pymaker.keys import register_keys
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSEthToken

from tests.helper import args


@pytest.fixture(scope="session")
def web3():
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

    collateral = [c for c in mcd.collaterals if c.gem.symbol() == "WETH"][0]
    assert isinstance(collateral.gem, DSEthToken)
    assert collateral.gem.deposit(amount).transact(from_address=address)


@pytest.fixture(scope="session")
def mcd(web3, our_address, keeper_address):
    return DssDeployment.from_json(web3=web3, conf=open("lib/pymaker/tests/config/addresses.json", "r").read())


@pytest.fixture(scope="session")
def c(mcd):
    return mcd.collaterals[1]


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

    # change in debt = (collateral balance * collateral price with safety margin) - CDP's stablecoin debt
    dart = urn.ink * ilk.spot - urn.art
    print(f'max_dart: ilk.spot is {ilk.spot}, dart is {dart}')

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


def simulate_frob(mcd: DssDeployment, collateral: Collateral, address: Address, dink: Wad, dart: Wad):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)
    assert isinstance(dink, Wad)
    assert isinstance(dart, Wad)

    urn = mcd.vat.urn(collateral.ilk, address)
    ilk = mcd.vat.ilk(collateral.ilk.name)

    print(f"[urn.ink={urn.ink}, urn.art={urn.art}] [ilk.art={ilk.art}, ilk.line={ilk.line}] [dink={dink}, dart={dart}]")
    print(f"[debt={str(mcd.vat.debt())} line={str(mcd.vat.line())}]")
    ink = urn.ink + dink
    art = urn.art + dart
    ilk_art = ilk.art + dart
    rate = ilk.rate

    gem = mcd.vat.gem(collateral.ilk, urn.address) - dink
    dai = mcd.vat.dai(urn.address) + Rad(rate * dart)
    debt = mcd.vat.debt() + Rad(rate * dart)

    # stablecoin debt does not increase
    cool = dart <= Wad(0)
    # collateral balance does not decrease
    firm = dink >= Wad(0)
    nice = cool and firm

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
    assert nice or safe

    assert Rad(ilk_art * rate) >= ilk.dust or (art == Wad(0))
    assert rate != Ray(0)
    assert mcd.vat.live()


def is_cdp_safe(ilk: Ilk, urn: Urn) -> bool:
    assert isinstance(urn, Urn)
    assert urn.art is not None
    assert ilk.rate is not None
    assert urn.ink is not None
    assert ilk.spot is not None

    #print(f'{urn.art} * {ilk.rate} <=? {urn.ink} * {ilk.spot}')
    return (Ray(urn.art) * ilk.rate) <= Ray(urn.ink) * ilk.spot


def create_unsafe_cdp(mcd: DssDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure CDP isn't already unsafe (if so, this shouldn't be called)
    urn = mcd.vat.urn(c.ilk, gal_address)
    assert is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn)
    assert urn.ink == Wad(0)
    assert urn.art == Wad(0)

    # Add collateral to gal CDP
    collateral_amount = Wad.from_number(collateral_amount)
    wrap_eth(mcd, gal_address, collateral_amount)
    c.approve(gal_address)
    assert c.adapter.join(gal_address, collateral_amount).transact(from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, collateral_amount, Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    dart = max_dart(mcd, c, gal_address) - Wad(1)
    simulate_frob(mcd, c, gal_address, Wad(0), dart)
    assert mcd.vat.frob(c.ilk, gal_address, Wad(0), dart).transact(from_address=gal_address)

    # Manipulate price to make gal CDP underwater
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    set_collateral_price(mcd, c, to_price)

    # Ensure the CDP is unsafe
    urn = mcd.vat.urn(c.ilk, gal_address)
    assert not is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn)
    return urn


def create_keeper(mcd: DssDeployment, c: Collateral, address=None):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    if address is None:
        address = Address(mcd.web3.eth.accounts[1])
    assert isinstance(address, Address)

    keeper = AuctionKeeper(args=args(f"--eth-from {address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=mcd.web3)
    keeper.approve()
    return keeper


@pytest.fixture()
def keeper(web3, c: Collateral, keeper_address: Address, mcd):
    return create_keeper(mcd, c, keeper_address)


@pytest.fixture()
def other_keeper(web3, c: Collateral, other_address: Address, mcd):
    return create_keeper(mcd, c, other_address)
