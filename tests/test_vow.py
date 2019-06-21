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
from tests.helper import args, wait_for_other_threads


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
    # {"MCD_MOM": "0xD3F7637ace900b381a0A6Bf878639E5BCa564B53", "MCD_VAT": "0x7dc681a82de642cf86cc05d6c938aA0021a6807F", "MCD_VOW": "0x68A75d6CaC097fFE5FC1e912EaDc8832bC1D8f36", "MCD_DRIP": "0x58B21768D30433481FbE87C2065Cc081eF982898", "MCD_PIT": "0x0D64bE75122D4Cb0F65776a973f3c03eb83177Ff", "MCD_CAT": "0x49A4177032a6cA5f419E764a154B6CE710418e6a", "MCD_FLAP": "0x90194dC5E16C203EE8debEc949130Ed60D97Af96", "MCD_FLOP": "0x27c232d542B3F9503c327Ff087582983E2086c61", "MCD_DAI": "0xdBA593D53D5C5AA91D73402DB3622d63463620Dd", "MCD_JOIN_DAI": "0xD2E5103366FEf1F6D387d0e11132Cef95ae3F8c8", "MCD_MOVE_DAI": "0x86a1f3308dA49e7b3C8e64a6702AD19f72Ca4aEB", "MCD_GOV": "0xD6be7670e94E88b28143F057944DAAA8900629AE", "COLLATERALS": ["WETH"], "WETH": "0x820f809525024513a5A45e74f5Cf36C67b98F2D7", "MCD_JOIN_WETH": "0xe058f7252743064ee497cF5Caa10F312B00691e9", "MCD_MOVE_WETH": "0x4dFcCEBCF5Ae068AE41503B93f7d4e8234087800", "MCD_FLIP_WETH": "0xec8e3dFdfD4665f19971B4ffE2a78b51095f349b", "MCD_SPOT_WETH": "0xc323B27F990C4AA3C9297Da8738d765Bac3ca8df", "PIP_WETH": "0xaCab49615c32e56a59097855a08d3653cAb0e473"}
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

    # mint MKR for the keeper
    assert d.mkr.mint(Wad.from_number(100)).transact()
    assert d.mkr.transfer(keeper_address, Wad.from_number(100)).transact()

    return d


@pytest.fixture(scope="session")
def c(mcd):
    return mcd.collaterals[0]


@pytest.fixture()
def flap_keeper(web3, c: Collateral, keeper_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flapper {mcd.flap.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--vow {mcd.vow.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def flop_keeper(web3, c: Collateral, keeper_address: Address, mcd):
    keeper = AuctionKeeper(args=args(f"--eth-from {keeper_address} "
                                     f"--flopper {mcd.flop.address} "
                                     f"--cat {mcd.cat.address} "
                                     f"--vow {mcd.vow.address} "
                                     f"--ilk {c.ilk.name} "
                                     f"--model ./bogus-model.sh"), web3=web3)

    keeper.approve()

    return keeper


@pytest.fixture()
def unsafe_cdp(our_address, gal_address, mcd, c: Collateral):
    # Add collateral to gal CDP
    assert c.adapter.join(Urn(gal_address), Wad.from_number(10)).transact(from_address=gal_address)
    assert mcd.pit.frob(c.ilk, Wad.from_number(10), Wad(0)).transact(from_address=gal_address)

    # Put gal CDP at max possible debt
    our_urn = mcd.vat.urn(c.ilk, gal_address)
    max_dart = our_urn.ink * mcd.pit.spot(c.ilk) - our_urn.art
    to_price = Wad(c.pip.read_as_int()) - Wad.from_number(1)
    assert mcd.pit.frob(c.ilk, Wad(0), max_dart).transact(from_address=gal_address)

    # Manipulate price to make gal CDP underwater
    assert c.pip.poke_with_int(to_price.value).transact(from_address=our_address)
    assert c.spotter.poke().transact()

    return mcd.vat.urn(c.ilk, gal_address)


@pytest.fixture()
def bid_id(unsafe_cdp: Urn, mcd, c: Collateral):
    # Bite gal CDP
    flip_id = mcd.cat.nflip()
    assert mcd.cat.bite(unsafe_cdp.ilk, unsafe_cdp).transact()

    # Kick one flip auction
    flip = mcd.cat.flips(flip_id)
    lump = mcd.cat.lump(flip.urn.ilk)
    assert mcd.cat.flip(flip, lump).transact()

    return c.flipper.kicks()

@pytest.mark.skip(reason="Needs updating to accommodate DSS changes")
class TestAuctionKeeperVow:
    def test_flap(self, our_address, flap_keeper, mcd):
        # given
        joy = mcd.vow.joy()
        awe = mcd.vow.awe()
        hump = mcd.vow.hump()
        bump = mcd.vow.bump()
        needed_joy = Wad.from_number(10) - joy + awe + hump + bump
        if needed_joy > Wad(0):
            assert mcd.dai_move.move(our_address, mcd.vow.address, needed_joy).transact(from_address=our_address)
        kicks = mcd.flap.kicks()

        # when
        flap_keeper.check_flap()

        # then
        assert mcd.flap.kicks() == kicks + 1

    def test_flop(self, flop_keeper, bid_id, mcd):
        print(mcd)
        # given
        kicks = mcd.flop.kicks()

        # when
        flop_keeper.check_flop()

        # then
        assert mcd.flop.kicks() == kicks + 1
