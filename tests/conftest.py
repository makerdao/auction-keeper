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
import math
import pytest

from mock import MagicMock
from typing import Optional
from web3 import Web3

from auction_keeper.logic import Stance
from auction_keeper.main import AuctionKeeper
from pymaker import Address, web3_via_http
from pymaker.approval import hope_directly
from pymaker.collateral import Collateral
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn
from pymaker.feed import DSValue
from pymaker.gas import NodeAwareGasPrice
from pymaker.keys import register_keys
from pymaker.model import Token
from pymaker.numeric import Wad, Ray, Rad
from pymaker.token import DSEthToken, DSToken
from tests.helper import time_travel_by


@pytest.fixture(scope="session")
def web3():
    # These details are specific to the MCD testchain used for pymaker unit tests.
    web3 = web3_via_http("http://0.0.0.0:8545", 3, 100)
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
    assert web3.eth.accounts[0] == "0x50FF810797f75f6bfbf2227442e0c961a8562F4C"
    return Address(web3.eth.accounts[0])


@pytest.fixture(scope="session")
def keeper_address(web3):
    assert web3.eth.accounts[1] == "0x57Da1B8F38A5eCF91E9FEe8a047DF0F0A88716A1"
    return Address(web3.eth.accounts[1])


@pytest.fixture(scope="session")
def other_address(web3):
    assert web3.eth.accounts[2] == "0x5BEB2D3aA2333A524703Af18310AcFf462c04723"
    return Address(web3.eth.accounts[2])


@pytest.fixture(scope="session")
def gal_address(web3):
    assert web3.eth.accounts[3] == "0x6c626f45e3b7aE5A3998478753634790fd0E82EE"
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
    return DssDeployment.from_node(web3=web3)


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
    assert urn.ink > Wad(0)
    ilk = mcd.vat.ilk(collateral.ilk.name)

    # change in art = (collateral balance * collateral price with safety margin) - vault's existing stablecoin debt
    dart = urn.ink * ilk.spot - Wad(Ray(urn.art) * ilk.rate)

    # change in debt must also take the rate into account
    dart = Wad(Ray(dart) / ilk.rate)

    print(f"max_dart for urn with ink={float(urn.ink)} and art={float(urn.art)} calculated as dart={float(dart)}")

    # prevent the change in debt from exceeding the collateral debt ceiling
    if (Rad(urn.art) + Rad(dart)) >= ilk.line:
        print("max_dart is avoiding collateral debt ceiling")
        dart = Wad(ilk.line - Rad(urn.art))

    # prevent the change in debt from exceeding the total debt ceiling
    debt = mcd.vat.debt() + Rad(ilk.rate * dart)
    line = Rad(mcd.vat.line())
    if (debt + Rad(dart)) >= line:
        print(f"debt {debt} + dart {dart} >= {line}; max_dart is avoiding total debt ceiling")
        dart = Wad(debt - Rad(urn.art))

    # ensure we've met the dust cutoff
    if Rad(urn.art + dart) < ilk.dust:
        print(f"max_dart is being bumped from {urn.art + dart} to {ilk.dust} to reach dust cutoff")
        dart = Wad(ilk.dust)

    return dart


def max_dart_for_ink(mcd: DssDeployment, collateral: Collateral, ink: Wad) -> Wad:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(ink, Wad)
    assert ink > Wad(0)

    ilk = mcd.vat.ilk(collateral.ilk.name)
    dart = Wad(Ray(ink) * ilk.spot / ilk.rate) - Wad(1)
    print(f"max_dart for ink={float(ink)} calculated as dart={float(dart)}; rate={float(ilk.rate)}")

    # prevent the change in debt from exceeding the total debt ceiling
    debt = mcd.vat.debt() + Rad(ilk.rate * dart)
    line = Rad(mcd.vat.line())
    if (debt + Rad(dart)) >= line:
        print(f"debt {debt} + dart {dart} >= {line}; max_dart is avoiding total debt ceiling")
        dart = Wad(debt - Rad(dart))

    # ensure we've met the dust cutoff
    if Rad(dart) < ilk.dust:
        print(f"max_dart is being bumped from {dart} to {ilk.dust} to reach dust cutoff")
        dart = Wad(ilk.dust)

    return dart


def reserve_dai(mcd: DssDeployment, c: Collateral, usr: Address, amount: Wad, extra_collateral=Wad.from_number(1)):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(usr, Address)
    assert isinstance(amount, Wad)
    assert amount > Wad(0)

    # Ensure dust limits are reached
    amount: Wad = max(amount, Wad(c.ilk.dust))

    # Determine how much collateral is needed
    ilk = mcd.vat.ilk(c.ilk.name)
    rate = ilk.rate  # Ray
    spot = ilk.spot  # Ray
    assert rate >= Ray.from_number(1)
    urn = mcd.vat.urn(ilk, usr)
    tab: Rad = (Rad(mcd.vat.dai(usr)) + Rad(amount)) * ilk.rate
    assert tab > Rad(0)
    print(f"attempting to reserve {amount} Dai using urn {urn}")
    # TODO: extra_collateral was a hack I'd like to remove
    ink_required = Wad(tab) * extra_collateral + Wad(1)
    dink = max(Wad(0), ink_required - urn.ink)
    if dink > Wad(0):
        print(f'ink={str(urn.ink)} art={str(urn.art)}; {str(dink)} more {ilk.name} is required to draw {str(amount)} Dai')
        wrap_eth(mcd, usr, dink)
        c.approve(usr)
        assert c.adapter.join(usr, dink).transact(from_address=usr)
    else:
        print(f"no additional collateral is required to draw {str(amount)} Dai")
    assert mcd.vat.frob(c.ilk, usr, dink, amount).transact(from_address=usr)
    assert mcd.vat.urn(c.ilk, usr).art >= Wad(amount)


def purchase_dai(amount: Wad, recipient: Address):
    assert isinstance(amount, Wad)
    assert isinstance(recipient, Address)

    m = mcd(web3())
    seller = gal_address(web3())
    reserve_dai(m, m.collaterals['ETH-C'], seller, amount)
    m.approve_dai(seller)
    m.approve_dai(recipient)
    assert m.dai_adapter.exit(seller, amount).transact(from_address=seller)
    assert m.dai.transfer_from(seller, recipient, amount).transact(from_address=seller)


def is_cdp_safe(ilk: Ilk, urn: Urn) -> bool:
    assert isinstance(urn, Urn)
    assert urn.art is not None
    assert ilk.rate is not None
    assert urn.ink is not None
    assert ilk.spot is not None

    #print(f'art={urn.art} * rate={ilk.rate} <=? ink={urn.ink} * spot={ilk.spot}')
    return (Ray(urn.art) * ilk.rate) <= Ray(urn.ink) * ilk.spot


def create_risky_cdp(mcd: DssDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address,
                     draw_dai=True) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    # Ensure vault isn't already unsafe (if so, this shouldn't be called)
    urn = mcd.vat.urn(c.ilk, gal_address)
    assert is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn)

    # Add collateral to gal vault if necessary
    c.approve(gal_address)
    token = Token(c.ilk.name, c.gem.address, c.adapter.dec())
    print(f"collateral_amount={collateral_amount} ink={urn.ink}")
    dink = collateral_amount - urn.ink
    if dink > Wad(0):
        vat_balance = mcd.vat.gem(c.ilk, gal_address)
        balance = token.normalize_amount(c.gem.balance_of(gal_address))
        print(f"before join: dink={dink} vat_balance={vat_balance} balance={balance} vat_gap={dink - vat_balance}")
        if vat_balance < dink:
            vat_gap = dink - vat_balance
            if balance < vat_gap:
                if c.ilk.name.startswith("ETH"):
                    wrap_eth(mcd, gal_address, vat_gap)
                else:
                    raise RuntimeError("Insufficient collateral balance")
            amount_to_join = token.unnormalize_amount(vat_gap)
            if amount_to_join == Wad(0):  # handle dusty balances with non-18-decimal tokens
                amount_to_join += token.unnormalize_amount(token.min_amount)
            assert c.adapter.join(gal_address, amount_to_join).transact(from_address=gal_address)
        vat_balance = mcd.vat.gem(c.ilk, gal_address)
        print(f"after join: dink={dink} vat_balance={vat_balance} balance={balance} vat_gap={dink - vat_balance}")
        assert vat_balance >= dink
        assert mcd.vat.frob(c.ilk, gal_address, dink, Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    dart = max_dart(mcd, c, gal_address) - Wad(1)
    if dart > Wad(0):
        print(f"Attempting to frob with dart={dart}")
        assert mcd.vat.frob(c.ilk, gal_address, Wad(0), dart).transact(from_address=gal_address)

    # Draw our Dai, simulating the usual behavior
    urn = mcd.vat.urn(c.ilk, gal_address)
    if draw_dai and urn.art > Wad(0):
        mcd.approve_dai(gal_address)
        assert mcd.dai_adapter.exit(gal_address, urn.art).transact(from_address=gal_address)
        print(f"Exited {urn.art} Dai from urn")
    return urn


def create_unsafe_cdp(mcd: DssDeployment, c: Collateral, collateral_amount: Wad, gal_address: Address,
                      draw_dai=True) -> Urn:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(gal_address, Address)

    create_risky_cdp(mcd, c, collateral_amount, gal_address, draw_dai)
    urn = mcd.vat.urn(c.ilk, gal_address)

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

    joy_before = mcd.vat.dai(mcd.vow.address)

    ink = Wad.from_number(10)
    art = max_dart_for_ink(mcd, c, ink) - Wad(1)
    assert art > Wad(0)
    wrap_eth(mcd, gal_address, ink)
    c.approve(gal_address)
    print(f"collateral={c.ilk.name}, ink={float(ink)}, art={float(art)}, joy_before={float(joy_before)}")
    assert c.adapter.join(gal_address, ink).transact(from_address=gal_address)
    assert mcd.vat.frob(c.ilk, gal_address, dink=ink, dart=art).transact(from_address=gal_address)
    joy = mcd.vat.dai(mcd.vow.address)
    awe = mcd.vat.sin(mcd.vow.address)
    # total surplus > total debt + surplus auction lot size + surplus buffer
    while float(joy) <= float(awe) + float(mcd.vow.bump()) + float(mcd.vow.hump()):
        print(f"joy={float(joy)}; waiting for fees to accumulate")
        time_travel_by(mcd.web3, 3)
        assert mcd.jug.drip(c.ilk).transact(from_address=gal_address)
        joy = mcd.vat.dai(mcd.vow.address)
        awe = mcd.vat.sin(mcd.vow.address)
    print(f"joy={float(joy)} > awe={float(awe)} + bump={float(mcd.vow.bump())} + hump={float(mcd.vow.hump())}")
    assert joy >= joy_before
    return mcd.vat.urn(c.ilk, gal_address)


def bite(mcd: DssDeployment, c: Collateral, unsafe_cdp: Urn) -> int:
    assert isinstance(mcd, DssDeployment)
    assert isinstance(c, Collateral)
    assert isinstance(unsafe_cdp, Urn)

    assert mcd.cat.can_bite(unsafe_cdp.ilk, unsafe_cdp)
    assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()
    bites = mcd.cat.past_bites(1)
    assert len(bites) == 1
    return c.flipper.kicks()


def repay_urn(mcd, c: Collateral, address: Address) -> bool:
    assert isinstance(c, Collateral)
    assert isinstance(address, Address)
    mcd.approve_dai(address)

    urn = mcd.vat.urn(c.ilk, address)
    if urn.art > Wad(0):
        vat_dai = mcd.vat.dai(address)
        tab: Wad = urn.art * c.ilk.rate
        wipe: Wad = mcd.vat.get_wipe_all_dart(c.ilk, address)
        # if we have any Dai, repay all or part of the urn
        if vat_dai > Rad(0):
            vat_dai = vat_dai / Rad(c.ilk.rate)  # adjust for Dai available for repayment
            repay_amount = min(wipe, tab, Wad(vat_dai))
            print(f"wipe={wipe}, tab={tab}, vat_dai={vat_dai}")
            print(f"{c.ilk.name} dust is {float(c.ilk.dust)}")
            print(f"repaying {repay_amount} Dai on {c.ilk.name} urn {address}; art={urn.art}")
            assert mcd.vat.frob(c.ilk, address, Wad(0), repay_amount*-1).transact(from_address=address)
            urn = mcd.vat.urn(c.ilk, address)
        else:
            print(f"{address} has no Dai to repay tab of {float(tab)}")
    else:
        print(f"{c.ilk.name} urn {address} has no debt")
    if urn.art == Wad(0):
        # withdraw all collateral if there's no debt
        if urn.ink > Wad(0):
            print(f"withdrawing {float(urn.ink)} {c.ilk.name} from urn {address}")
            assert mcd.vat.frob(c.ilk, address, urn.ink*-1, Wad(0)).transact(from_address=address)
            urn = mcd.vat.urn(c.ilk, address)

    if urn.ink == Wad(0) and urn.art == Wad(0):
        print(f"{c.ilk.name} urn {address} was fully repaid")
        return True
    else:
        print(f"{c.ilk.name} urn {address} left ink={urn.ink} art={urn.art}")
        return False


def liquidate_urn(mcd, c: Collateral, address: Address, bidder: Address):
    assert isinstance(c, Collateral)
    assert isinstance(address, Address)
    assert isinstance(bidder, Address)
    c.flipper.approve(mcd.vat.address, approval_function=hope_directly(from_address=bidder))

    # Ensure the CDP isn't safe
    urn = mcd.vat.urn(c.ilk, address)
    dart = max_dart(mcd, c, address) - Wad.from_number(1)
    assert mcd.vat.frob(c.ilk, address, Wad(0), dart).transact(from_address=address)
    set_collateral_price(mcd, c, Wad.from_number(66))
    if is_cdp_safe(mcd.vat.ilk(c.ilk.name), urn):
        print(f"{c.ilk.name} urn {address} remains safe after dropping collateral price; not liquidating")
        return

    # Determine how many bites will be required
    dunk: Rad = mcd.cat.dunk(c.ilk)
    box: Rad = mcd.cat.box()
    urn = mcd.vat.urn(c.ilk, address)
    bites_required = math.ceil(urn.art / Wad(dunk))
    print(f"art={float(urn.art)} and dunk={float(dunk)} so {bites_required} bites are required")
    first_kick = c.flipper.kicks() + 1

    while urn.art > Wad(0):
        box_kick = c.flipper.kicks() + 1
        print(f"art={float(urn.art)} litter={float(mcd.cat.litter())} next bite will be for {float(min(Rad(urn.art), dunk))} Dai")

        while mcd.cat.litter() + min(Rad(urn.art), dunk) < box and urn.art > Wad(0):
            # Bite and bid on each auction
            print(f"biting {(c.flipper.kicks() + 1)} ({(c.flipper.kicks() + 1) - first_kick} of {bites_required})")
            kick = bite(mcd, c, urn)
            auction = c.flipper.bids(kick)
            reserve_dai(mcd, c, bidder, Wad(auction.tab))
            print(f"bidding tab {auction.tab} on auction {kick} for {auction.lot} with {mcd.vat.dai(bidder)} Dai remaining")
            assert c.flipper.tend(kick, auction.lot, auction.tab).transact(from_address=bidder)
            urn = mcd.vat.urn(c.ilk, address)

        time_travel_by(mcd.web3, c.flipper.ttl())
        for kick in range(box_kick, c.flipper.kicks() + 1):
            print(f"dealing {kick} ({kick - first_kick} of {bites_required})")
            assert c.flipper.deal(kick).transact()

    set_collateral_price(mcd, c, Wad.from_number(200))
    assert urn.art == Wad(0)
    if urn.ink > Wad(0):
        print(f"withdrawing {float(urn.ink)} {c.ilk.name} from urn {address}")
        assert mcd.vat.frob(c.ilk, address, urn.ink * -1, Wad(0)).transact(from_address=address)
    assert urn.ink == Wad(0)


def flog_and_heal(web3: Web3, mcd: DssDeployment, past_blocks=8, kiss=True, require_heal=True):
    # Raise debt from the queue (note that vow.wait is 0 on our testchain)
    bites = mcd.cat.past_bites(past_blocks)
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


def simulate_model_output(model: object, price, gas_price: Optional[int] = None):
    assert isinstance(price, Wad) or isinstance(price, Ray)
    assert isinstance(gas_price, int) or gas_price is None
    model.get_stance = MagicMock(return_value=Stance(price=price, gas_price=gas_price))


def get_node_gas_price(web3: Web3):
    class DummyGasStrategy(NodeAwareGasPrice):
        def get_gas_price(self, time_elapsed: int) -> Optional[int]:
            return self.get_node_gas_price()

    assert isinstance(web3, Web3)
    dummy = DummyGasStrategy(web3)
    return dummy.get_node_gas_price()
