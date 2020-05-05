# Thrifty Keeper

This repository is a fork of https://github.com/makerdao/auction-keeper.  Before using this repository, you should refer to the main repo instructions for understanding keeper architecture, installation, and bidding on flip auctions.

## Motivation:  

Keepers are a critical part of the DAI infrastructure and the more people that run them the better for DAI.  There are several difficulties, however, running keepers profitably.  First- when you store your DAI in the bidding contract, you don't earn the DSR.  Second- profitable auctions to bid on are typically rare and can occur at any time.  If you win an auction, you may want to sell the collateral to avoid downside risk especially when markets are falling (which is typically when most profitable auctions occur).

Therefore, this keeper provides the following updates to the standard design:

- Your dai is stored in the DSR by default.  If an auction is ongoing and there is a profitable bid to make, the necessary amount of DAI is removed from the DSR and deposited into the Vat to make the bid. 

- You can specify a minimum profit margin (adjusted for round trip gas costs) that a bid must satisfy before your Dai is desposited in the Vat.  Futher, you can adjust this profit margin for times when there are large amounts of collateral up for auction - typically when the best opportunities for profit exist (who can forget the $0 ETH up for sale on black thursday?)

- Once the auction is over, if you have won, your ETH can be programatically sold for DAI (using the 0x api).  Your DAI is then redeposited in the DSR when the auctions have ended. 

- While this keeper is NOT guaranteed to earn you a profit, it will allow you to earn the DSR on your DAI and submit bids only if they look profitable. 



## Installation

This project uses *Python 3.6.6*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/makerdao/thrifty-keeper.git
cd thrifty-keeper
git submodule update --init --recursive
pip3 install -r requirements.txt
```

For some known Ubuntu and macOS issues see the [pymaker](https://github.com/makerdao/pymaker) README.


## Usage

In addition to the standard keeper options, thrifty keeper provides the following additional options to customize your keeper:

* --profit-margin:  The minimum profit you require to make a bid after accouting for gas costs.  For example, if ETH price is 500 DAI/ETH, the lot for sale is 1 ETH, and round trip gas costs are estimated at 1.5 DAI/ETH, a profit margin of 2% will result in the keeper placing a bid at 488.7 BAT/ETH assuming that it satisfies the minimum bid increment over any existing bid.

* --max-gem-balance :  The maximum amount of the collateral to store in your keeper account (e.g. ETH, BAT).  Any amount above this will be sold for DAI after you win an auction.

* --max-gem-sale:  The maximum amount of collateral to sell in a single transaction (to avoid slippage)

--tab-discount: 




## Gas price strategy

Auction keeper can use one of several sources for the initial gas price of a transaction:  
 * **Ethgasstation** if a key is passed as `--ethgasstation-api-key` (e.g. `--ethgasstation-api-key MY_API_KEY`)  
 * **Etherchain.org** if keeper started with `--etherchain-gas-price` switch  
 * **POANetwork** if keeper started with `--poanetwork-gas-price` switch. An alternate URL can be passed as `--poanetwork-url`,
    that is useful when server hosted locally (e.g. `--poanetwork-url http://localhost:8000`)  
 * The `--fixed-gas-price` switch allows specifying a **fixed** initial price in Gwei (e.g. `--fixed-gas-price 12.4`) 
 
When using an API source for initial gas price, `--gas-initial-multiplier` (default `1.0`, or 100%) tunes the initial 
value provided by the API.  This is ignored when using `--fixed-gas-price` and when no strategy is chosen.  If no 
initial gas source is configured, or the gas price API produces no result, then the keeper will start with a price of 
10 Gwei.

Auction keeper periodically attempts to increase gas price when transactions are queueing.  Every 30 seconds, a 
transaction's gas price will be multiplied by `--gas-reactive-multiplier` (default `2.25`, or 225%) until it is mined or 
`--gas-maximum` (default 5000 Gwei) is reached.  
Note that [Parity](https://wiki.parity.io/Transactions-Queue#dropping-conditions), as of this writing, requires a 
minimum gas increase of `1.125` (112.5%) to propogate transaction replacement; this should be treated as a minimum 
value unless you want replacements to happen less frequently than 30 seconds (2+ blocks). 

This gas strategy is used by keeper in all interactions with chain.  When sending a bid, this strategy is used only 
when the model does not provide a gas price.  Unless your price model is aware of your transaction status, it is 
generally advisable to allow the keeper to manage gas prices for bids, and not supply a `gasPrice` in your model.






## License

See [COPYING](https://github.com/makerdao/auction-keeper/blob/master/COPYING) file.

### Disclaimer

YOU (MEANING ANY INDIVIDUAL OR ENTITY ACCESSING, USING OR BOTH THE SOFTWARE INCLUDED IN THIS GITHUB REPOSITORY) EXPRESSLY UNDERSTAND AND AGREE THAT YOUR USE OF THE SOFTWARE IS AT YOUR SOLE RISK.
THE SOFTWARE IN THIS GITHUB REPOSITORY IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
YOU RELEASE AUTHORS OR COPYRIGHT HOLDERS FROM ALL LIABILITY FOR YOU HAVING ACQUIRED OR NOT ACQUIRED CONTENT IN THIS GITHUB REPOSITORY. THE AUTHORS OR COPYRIGHT HOLDERS MAKE NO REPRESENTATIONS CONCERNING ANY CONTENT CONTAINED IN OR ACCESSED THROUGH THE SERVICE, AND THE AUTHORS OR COPYRIGHT HOLDERS WILL NOT BE RESPONSIBLE OR LIABLE FOR THE ACCURACY, COPYRIGHT COMPLIANCE, LEGALITY OR DECENCY OF MATERIAL CONTAINED IN OR ACCESSED THROUGH THIS GITHUB REPOSITORY.
