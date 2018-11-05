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
import pytest

from pymaker.deployment import DssDeployment
from pymaker.dss import Urn, Collateral
from web3 import Web3, HTTPProvider

from auction_keeper.main import AuctionKeeper
from pymaker import Address
from pymaker.numeric import Wad
from tests.helper import args, TransactionIgnoringTest, wait_for_other_threads


@pytest.fixture(scope="session")
def web3():
    web3 = Web3(HTTPProvider("http://localhost:8555"))
    web3.eth.defaultAccount = web3.eth.accounts[0]
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


@pytest.fixture(scope="session")
def d(web3, our_address, keeper_address, gal_address):
    # dss = """
    # {"MCD_VAT": "0x08a3a91978B277c5797747A3671bDb6eE86e900E", "MCD_VOW": "0x7ef07c8DfddEECC23D50672b09310e45C8692ad2", "MCD_DRIP": "0xdc127E4DfF5F68740B8e21dEA687A4C3C690c176", "MCD_PIT": "0xaccbA2bB146405241507D7F3e39B85C5d1179d2B", "MCD_CAT": "0x41541A8692e00b9F5db706305dA1ee395Ba4680E", "MCD_FLOP": "0x5958E69d5795823F0F84b2ccbCE8D210cb67f418", "MCD_DAI": "0x787Cb94B57C23b9617265F1a6B80569d10dAaa42", "MCD_JOIN_DAI": "0xCc13a1a2E5AE9F6eC05CA7aF762967c5BD1Dd53f", "MCD_MOVE_DAI": "0x18792385d6c9AE2236cAc48473eb30D7d669BfFC", "MCD_GOV": "0xbE8Ae37bE4a1b1e22bAFD0cDdD921bc8FD5aD134", "COLLATERALS": ["WETH"], "WETH": "0x4Cdd635f050f9ca5bD7533D8c86044c4B86339A5", "MCD_JOIN_WETH": "0x050B6E24a805A027E3a31e7D4dE7E79A88A84e6D", "MCD_MOVE_WETH": "0x2ae154E870F53AC72f0D2E39FA2bb3a812b6A55d", "MCD_FLIP_WETH": "0x0953b1f31BBFA2633d7Ec92eb0C16511269aD4d0", "MCD_SPOT_WETH": "0x3731b266f67A9307CfaC6407D893070944F0684F", "PIP_WETH": "0x4C4EC6939152E7cD455D6586BC3eb5fF22ED94BE"}
    # """
    # return DssDeployment.from_json(web3=web3, conf=dss)
    d = DssDeployment.deploy(web3=web3, debt_ceiling=Wad.from_number(100000000))
    c = d.collaterals[0]
    assert d.pit.file_line(c.ilk, Wad.from_number(100000000)).transact()  # Set collateral debt ceiling
    assert d.cat.file_lump(c.ilk, Wad.from_number(100)).transact()  # Set liquidation Quantity of c at 100

    # mint gem for cdp frob() by gal_address and our_address to draw dai
    assert c.gem.mint(Wad.from_number(2000000)).transact()
    assert c.gem.transfer(gal_address, Wad.from_number(1000000)).transact()

    # Require to join the adapter
    assert c.gem.approve(c.adapter.address).transact()
    assert c.gem.approve(c.adapter.address).transact(from_address=gal_address)

    # draw dai for our_address
    assert c.adapter.join(Urn(our_address), Wad.from_number(1000000)).transact()
    assert d.pit.frob(c.ilk, Wad.from_number(1000000), Wad.from_number(1000000)).transact()
    assert d.dai_move.move(our_address, keeper_address, Wad.from_number(10000)).transact()

    return d


@pytest.fixture(scope="session")
def c(d: DssDeployment):
    return d.collaterals[0]


@pytest.fixture()
def keeper(web3, c: Collateral, keeper_address: Address, d: DssDeployment):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--cat {d.cat.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def other_keeper(web3, c: Collateral, other_address: Address, d: DssDeployment):
    keeper = AuctionKeeper(args=args(f"--eth-from {other_address} "
                                     f"--flipper {c.flipper.address} "
                                     f"--cat {d.cat.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def unsafe_cdp(our_address, gal_address, d: DssDeployment, c: Collateral):
    # Add collateral to gal CDP
    assert c.adapter.join(Urn(gal_address), Wad.from_number(1)).transact(from_address=gal_address)
    assert d.pit.frob(c.ilk, Wad.from_number(1), Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    our_urn = d.vat.urn(c.ilk, gal_address)
    max_dart = our_urn.ink * d.pit.spot(c.ilk) - our_urn.art
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    assert d.pit.frob(c.ilk, Wad(0), max_dart).transact(from_address=gal_address)

    # Manipulate price to make gal CDP underwater
    assert c.pip.poke_with_int(to_price.value).transact(from_address=our_address)
    assert c.spotter.poke().transact()

    return d.vat.urn(c.ilk, gal_address)


class TestAuctionKeeperBite(TransactionIgnoringTest):
    def test_bite_and_flip(self, c: Collateral, keeper: AuctionKeeper, d: DssDeployment, unsafe_cdp: Urn):
        # given
        nflip = d.cat.nflip()
        nkick = c.flipper.kicks()

        # when
        keeper.check_cdps()
        wait_for_other_threads()

        # then
        urn = d.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been biten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert d.cat.nflip() == nflip + 1  # One more flip available
        assert c.flipper.kicks() == nkick +1  # One auction started


    def test_bite_only(self, other_keeper: AuctionKeeper, d: DssDeployment, c: Collateral, unsafe_cdp: Urn):
        # given
        nflip = d.cat.nflip()
        nkick = c.flipper.kicks()

        # when
        other_keeper.check_cdps()
        wait_for_other_threads()

        # then
        urn = d.vat.urn(unsafe_cdp.ilk, unsafe_cdp.address)
        assert urn.art == Wad(0)  # unsafe cdp has been biten
        assert urn.ink == Wad(0)  # unsafe cdp is now safe ...
        assert d.cat.nflip() == nflip + 1 # One more flip available
        assert c.flipper.kicks() == nkick  # No auction started because no available fund to tend()
