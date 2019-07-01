# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 bargst
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

from pymaker.deployment import DssDeployment
from pymaker.dss import Urn, Collateral
from web3 import Web3, HTTPProvider

from auction_keeper.main import AuctionKeeper
from pymaker import Address
from pymaker.feed import DSValue
from pymaker.keys import register_keys
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSEthToken

from tests.helper import args, TransactionIgnoringTest, wait_for_other_threads


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

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(urn.art) + Rad(dart)) >= ilk.line:
        dart = Wad(ilk.line - Rad(urn.art))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = mcd.vat.debt() + Rad(ilk.rate * dart)
    line = Rad(ilk.line)
    if (debt + Rad(dart)) >= line:
        dart = Wad(debt - Rad(urn.art))

    assert dart > Wad(0)
    return dart


@pytest.fixture(scope="session")
def mcd(web3, our_address, keeper_address):

    mcd = DssDeployment.from_json(web3=web3, conf=open("lib/pymaker/tests/config/addresses.json", "r").read())
    c = mcd.collaterals[0]

    # draw dai for our_address
    collateral_amount = Wad.from_number(4)
    wrap_eth(mcd, our_address, collateral_amount)
    c.approve(our_address)
    assert c.adapter.join(our_address, collateral_amount).transact()
    assert mcd.vat.frob(c.ilk, urn_address=our_address, collateral_owner=our_address, dai_recipient=keeper_address,
                        dink=collateral_amount, dart=Wad.from_number(500)).transact()
    mcd.approve_dai(keeper_address)
    assert mcd.dai_adapter.exit(keeper_address, Wad.from_number(500))

    return mcd


@pytest.fixture(scope="session")
def c(mcd):
    return mcd.collaterals[0]


@pytest.fixture()
def keeper(web3, c: Collateral, keeper_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)
    keeper.approve()
    return keeper


@pytest.fixture()
def other_keeper(web3, c: Collateral, other_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {other_address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)
    keeper.approve()
    return keeper


@pytest.fixture()
def unsafe_cdp(our_address, gal_address, mcd, c: Collateral):
    # Add collateral to gal CDP
    wrap_eth(mcd, gal_address, Wad.from_number(1))
    c.approve(gal_address)
    assert c.adapter.join(gal_address, Wad.from_number(1)).transact(from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, Wad.from_number(1), Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    dart = max_dart(mcd, c, gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, Wad(0), dart).transact(from_address=gal_address)

    # Manipulate price to make gal CDP underwater
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    set_collateral_price(mcd, c, to_price)

    return mcd.vat.urn(c.ilk, gal_address)


class TestAuctionKeeperBite(TransactionIgnoringTest):
    def test_bite_and_flip(self, c: Collateral, keeper: AuctionKeeper, mcd, unsafe_cdp: Urn):
        # given
        assert len(mcd.active_auctions()["flips"][c.ilk.name]) == 0

        # when
        keeper.check_cdps()
        wait_for_other_threads()

        # then
        urn = mcd.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been biten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert c.flipper.kicks() == 1  # One auction started
