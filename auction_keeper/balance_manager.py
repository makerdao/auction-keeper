
import requests
import logging
import time
import asyncio
import threading

from pymaker.dsr import Dsr
from pymaker.numeric import Wad, Rad
from pymaker import Transact, Address

import abis as abis

class Balance_Manager():

    logger = logging.getLogger()

    def __init__(self, address, web3, dss, ilk, gem_join, vat_target, max_eth_balance, max_eth_sale, profit_margin, tab_discount, bid_start_time):
        self.our_address = address
        self.web3 = web3
        self.weth_address = Address(abis.weth_address)
        self.weth_abi = abis.weth_abi
        self.weth_contract = self.web3.eth.contract(address=abis.weth_address, abi=self.weth_abi)
        self.dss = dss
        self.dsr = Dsr(self.dss, self.our_address)
        self.ilk = ilk
        self.gem_join = gem_join
        self.vat_target = vat_target
        self.max_eth_balance = max_eth_balance #max eth balance for keeper
        self.max_eth_sale = max_eth_sale #max lot to sell in single transaction to avoid slippage
        self.profit_margin = profit_margin
        self.bid_start_time = bid_start_time
        self.start_time = time.time()
        self.round_trip_gas = 950000 #total gas to witdraw, bid, sell, redeposit DAI from DSR
        self.user_proxy = None
        self.dsr_balance = None
        self.vat_balance = None
        self.auction_tab = {}
        self.time_log = {}
        self.log30 = {}
        self.log5 = {}
        self.bid_checker = {}
        self.auc_withdraw = {}
        self.tab_discount = tab_discount
        self.high_threshold = tab_discount[0]
        self.high_discount = tab_discount[1]
        self.low_threshold = tab_discount[2]
        self.low_discount = tab_discount[3]

    def startup(self, gasprice):
        logging.info(f"")
        logging.info(f"***** WELCOME TO THE THRIFTY KEEPER *****")
        self.dsr_approve(gasprice)
        self.threader('unload', gasprice)
        self.log_balances()
        self.report_margin()
        logging.info(f"")
    
    def threader(self, func, gasprice):
        if func is 'unload':
            vat_eth_balance = self.get_vat_eth_balance()
            if vat_eth_balance > Wad.from_number(self.max_eth_balance):
                threading.Thread(target=self.unload, args=(gasprice, vat_eth_balance),daemon=False).start()
            else:
                return
        elif func is 'save':
            vat_dai_balance = self.get_vat_balance()
            if vat_dai_balance == Wad(0): 
                return
            else:
                threading.Thread(target=self.save, args=(gasprice, vat_dai_balance),daemon=False).start() 

    def unload(self, gasprice, vat_eth_balance):
        self.check_gas_station(gasprice)
        self.withdraw_eth(gasprice, vat_eth_balance)
        self.unwrap_weth(gasprice)
        self.sell_eth_for_dai()
    
    def save(self, gasprice, vat_dai_balance):
        self.vat_withdraw(gasprice, vat_dai_balance)
        self.dsr_add(gasprice)
    
    def check_gas_station(self, gasprice):
        while True:
            if gasprice.gas_station is None:
                break
            elif gasprice.gas_station._fast_price:
                break
            else:
                time.sleep(1)
    
    def withdraw_eth(self, gasprice, vat_eth_balance):
        self.logger.info(f"Exiting {round(vat_eth_balance.__float__(),3)} {self.ilk.name} from the Vat")
        self.gem_join.exit(self.our_address, vat_eth_balance).transact(gas_price=gasprice)
       
        
    def unwrap_weth(self, gas_price):
        weth_balance = self.weth_contract.functions.balanceOf(self.our_address.address).call()
        if weth_balance > 0:
            withdraw = Transact(self, self.web3, self.weth_abi, self.weth_address, self.weth_contract, 'withdraw', [weth_balance])
            withdraw.transact (gas_price=gas_price)
            time.sleep(1)
            eth_balance = self.web3.eth.getBalance(self.our_address.address)
            self.logger.info(f"New ETH balance: {eth_balance/1e18}")
        else:
            logging.info(f"No WETH to unwrap")
    
    def report_margin(self):
        if self.high_threshold < self.low_threshold: #user entry check transpose
            x = self.high_threshold
            y = self.high_discount
            self.high_threshold = self.low_threshold
            self.low_threshold = x
            self.high_discount = self.low_discount
            self.low_discount = y
    
        high_threshold = "{:,}".format(int(self.high_threshold))
        low_threshold = "{:,}".format(int(self.low_threshold))
        logging.info(f"Base bid profit margin = {round(self.profit_margin*100, 3)}%")
        logging.info(f"Bid profit margin = {round((self.profit_margin + self.low_discount)*100, 3)}% when the sum of all active auction tabs is > {low_threshold} DAI")
        logging.info(f"Bid profit margin = {round((self.profit_margin + self.high_discount)*100, 3)}% when the sum of all active auction tabs is > {high_threshold} DAI")
        logging.info(f"If you win an auction, the ETH collateral will be sold until there is {self.max_eth_balance} ETH remaining in your keeper account ")
        logging.info(f"Max ETH sale amount in a single transaction is {self.max_eth_sale} ETH")
        logging.info(f"You will not submit bids until there are less than {self.bid_start_time}m left in the auction")
        logging.info(f"*****")
        
    def log_balances(self):
        dai_balance = self.get_dai_balance().__float__()
        dsr_balance = self.get_dsr_balance().__float__()
        eth_balance = self.web3.eth.getBalance(self.our_address.address)/1e18
        vat_balance = self.get_vat_balance().__float__()
        vat_eth_balance = self.get_vat_eth_balance().__float__()
        vat_target = self.vat_target.__float__()
        self.logger.info(f"Keeper Dai Balance =  {round(dai_balance,2)}")
        self.logger.info(f"Keeper DSR Balance = {round(dsr_balance,1)}")
        logging.info(f"Keeper ETH Balance = {round(eth_balance, 3)}")
        self.logger.info(f"Vat DAI Balance = {round(vat_balance,3)}")
        logging.info(f"Vat ETH Balance = {round(vat_eth_balance, 3)}")
        self.logger.info(f"Vat DAI Target = {round(vat_target,1)}")

    def get_dai_balance(self):
        return Wad(self.dsr.mcd.dai.balance_of(self.our_address))
    
    def get_dsr_balance(self):
        if self.dsr.has_proxy():
            user_proxy = self.dsr.get_proxy()
            return self.dsr.get_balance(user_proxy.address)
        else:
            return None

    def get_vat_balance(self):
        return Wad(self.dss.vat.dai(self.our_address))
    
    def get_vat_eth_balance(self):
        return Wad(self.dss.vat.gem(self.ilk, self.our_address))

    def add_tab(self):
        x = Rad(0)
        for value in self.auction_tab.values():
            x = x + value
        return x
    
    def get_tab_discount(self):
        tot_tab = self.add_tab()
        if tot_tab > Rad.from_number(self.high_threshold):
            discount = self.high_discount
        elif tot_tab > Rad.from_number(self.low_threshold):
            discount = self.low_discount
        else:
            discount = 0
        return(discount)
    
    def register_tab(self, auction_id, tab):
        if auction_id not in self.auction_tab.keys():
            self.auction_tab[auction_id] = tab
            tot_tab = self.add_tab()
            t = round(tab.__float__(), 3)
            self.logger.info(f"Registering auction {auction_id} with tab of {t} DAI.  Total of all active tabs is now {round(tot_tab.__float__(), 3)} DAI")
        

    
    def analyze_profit(self, gas_price, feed_price, lot, end, current_price, beg, auction_id):
        #gas estimates:
        #dsr_withdraw = 160000
        #vat_deposit = 50500
        #bid = 93000
        #deal = 52000
        #exit_weth = 59500
        #unwrap = 25000
        #sell_eth = 250000 x 2
        #vat withdraw = 80000
        #dsr_deposit = 160000

        def log_auction_stats():
            tot_tab = self.add_tab()
            num_auctions = len(self.auction_tab.keys())
            tab_discount = self.get_tab_discount()
            time_to_bid = int((time_left/60)-self.bid_start_time)
            logging.info(f"*****")
            self.logger.info(f"Auction id: {auction_id}")
            logging.info(f"Time left: {int(time_left/60)}m")
            logging.info(f"Auction tab: {round(self.auction_tab[auction_id].__float__(),3)} DAI")
            logging.info(f"Total of {num_auctions} active auctions for {round(tot_tab.__float__(), 3)} DAI. Tab discount: {tab_discount*100}%")
            logging.info(f"Lot size: {round(lot,4)} ETH")
            self.logger.info(f"Gas cost: {round(gas_cost_dai, 3)} DAI")
            self.logger.info (f"Market feed price: {round(feed_price, 2)} ETH/DAI")
            self.logger.info(f"Current bid price: {round(current_price, 2)} ETH/DAI")
            self.logger.info(f"Your profit price: {round(profit_price_daieth, 2)} ETH/DAI")
            self.logger.info(f"Current bid profit margin: {round(margin, 2)} %")
            logging.info(f"Your min profit margin: {round(((self.profit_margin+tab_discount)*100), 2)}% ")
            if profit_price_daieth > current_price:
                self.logger.info(f"Looks profitable to bid")
                if bidable:
                    logging.info(f"Your profit price is above the min bid increment.")
                    logging.info(f"Min new bid = {round(current_price*beg, 2)}")
                else:
                    logging.info(f"Your profit price is below the min bid increment.")
                    logging.info(f"Min new bid = {round(current_price*beg, 2)}")
            else:
                logging.info(f"Doesn't look profitable to bid.")
            if time_left > self.bid_start_time*60:
                logging.info(f"Too much time left. Will consider bidding in {time_to_bid} minutes.")
                logging.info ("Leaving your DAI in the DSR for now")
            logging.info(f"*****")

        def calc_margin():

            #Estimate gas costs in dai of exiting DSR, bidding, selling, redeposit
            gp = gas_price.get_gas_price(61) #fast gas price
            gas_cost_dai = self.round_trip_gas * feed_price * gp * 1e-18
            
            #Determine profit margin to discount feed_price
            tab_discount = self.get_tab_discount() #additional discount when large CDPs are being auctioned
            target_margin = self.profit_margin + tab_discount
            
            #Gross revenue from sale of dai at market price
            sell_amt_dai = (lot * feed_price)
            #Auction cost in dai at currently bid price
            bid_dai = (lot * current_price) + gas_cost_dai
            #Profit margin of current bid
            margin =  (sell_amt_dai - bid_dai)/bid_dai * 100

            #Price per ETH that provides target profit margin after gas costs 
            profit_price_daieth = (sell_amt_dai-((1+target_margin)*gas_cost_dai))/((1+target_margin)*lot)

            #Check if bid price can be protected by beg
            discount = ((beg - 1)/2) + 1
            best_bid = profit_price_daieth / discount
            if (best_bid > current_price * beg):
                profit_price_daieth = best_bid
            
            if profit_price_daieth > current_price * beg:
                bidable = True
            else:
                bidable = False
            return(profit_price_daieth, margin, gas_cost_dai, bidable)

        def check_new_bid(current_price, id):
            if id in self.bid_checker.keys():
                prior_bid = self.bid_checker[id]
            else:
                self.bid_checker[id] = current_price
                return False
            new_bid = current_price
            if new_bid == prior_bid:
                return False
            elif new_bid > prior_bid:
                self.bid_checker[id] = new_bid
                return True
        
        try:
            feed_price = feed_price.__float__()
            current_price = current_price.__float__()
            lot = lot.__float__()
            beg = beg.__float__()
            time_left = end - time.time()
            new_bid = check_new_bid(current_price, id)

            (profit_price_daieth, margin, gas_cost_dai, bidable) = calc_margin()

            if new_bid:
                logging.info(f"New bid detected")
                log_auction_stats()

            if time_left > (self.bid_start_time * 60):
                if auction_id not in self.time_log.keys():
                    logging.info(f"Initial auction stats")
                    self.time_log[auction_id] = True
                    log_auction_stats()
                return None
        
            if time_left <= (self.bid_start_time * 60) and not bidable and auction_id not in self.log30.keys():
                logging.info(f"Open for bidding")
                self.log30[auction_id] = True
                log_auction_stats()
            
            elif time_left <= 300 and not bidable and auction_id not in self.log5.keys():
                logging.info(f"5 min left")
                self.log5[auction_id] = True
                log_auction_stats()
            
            if bidable:
                logging.info(f"Bidable")
                log_auction_stats()
            
            if profit_price_daieth > current_price and bidable:
                return Wad.from_number(profit_price_daieth)
            else:
                return None
            
        except Exception as e:
            self.logger.info(f"{e}")
            return None


    def sell_eth_for_dai(self):

        def get0x(sell_amount):
            parameters = {
            'buyToken' : 'DAI',
            'sellToken' : 'ETH',
            'sellAmount' : str(int(sell_amount))
            }
            url = 'https://api.0x.org/swap/v0/quote'
            response = requests.get(url, params=parameters)
            if response.status_code == 200:
                rawdict = response.json()
                txdict = {}
                txdict['nonce'] = self.web3.eth.getTransactionCount(self.our_address.address)
                txdict['to'] = self.web3.toChecksumAddress(rawdict['to'])
                txdict['value'] = int(rawdict['value'])
                txdict['gas'] = int(rawdict['gas']) + 300000
                txdict['gasPrice'] = int(rawdict['gasPrice'])
                txdict['data']= rawdict['data']
                return txdict
            else:
                return False
            
        def determine_sale_info(balance):
            total_sell = (balance - self.max_eth_balance)/1e18
            if total_sell > self.max_eth_sale:
                num_sales = int(total_sell/self.max_eth_sale) + 1
            else:
                num_sales = 1
            sale_amount = total_sell/num_sales*1e18
            return (sale_amount, num_sales)

        while True:
            balance = self.web3.eth.getBalance(self.our_address.address)
            self.logger.info(f"ETH balance: {round(balance/1e18,3)}")
            if balance > self.web3.toWei(self.max_eth_balance, 'ether'):
                (sell_amount, num_sales) = determine_sale_info(balance)
                tot_sale = round((balance/1e18 - self.max_eth_balance), 3)
                self.logger.info(f"Selling {tot_sale} ETH for DAI to maintain {self.max_eth_balance} ETH in account")
                for x in range (num_sales):
                    self.logger.info(f"Checking 0x API")
                    txdict = get0x(sell_amount)
                    if txdict:
                        self.logger.info(f"Selling {round(sell_amount/1e18,3)} ETH")
                        txhash = self.web3.eth.sendTransaction(txdict)
                        self.web3.eth.waitForTransactionReceipt(txhash)
                        self.logger.info(f"Done")
                        if (num_sales - x) > 1:
                            time.sleep(60)
                    else:
                        time.sleep(1)
                        self.logger.info(f"0x down")
                self.log_balances()   
            else:
                self.logger.info(f"Keeper balance <= {self.max_eth_balance} ETH")
                break
        
    
    def dsr_approve(self, gas_price):
         # Checking if the user has a DS-Proxy - if not, we build one.
        if self.dsr.has_proxy() == False:
            self.logger.info(f"No DS-Proxy found - Building new proxy...")
            self.dsr.build_proxy().transact(gas_price = gas_price)
            time.sleep(1)
            self.user_proxy = self.dsr.get_proxy()
            self.logger.info(f"Built new proxy at: {self.user_proxy.address.address}")

            # Approving the DS-Proxy to move Dai from our wallet to the DSR
            logging.info(f"Approving account to spend Dai...")
            self.dsr.mcd.dai.approve(self.user_proxy.address.address).transact(gas_price=gas_price)
            self.logger.info(f"Approved DS-Proxy to spend Dai. Keeper's DSR is now configured")

        if self.dsr.has_proxy() == True:
            self.user_proxy = self.dsr.get_proxy()
            self.logger.info(f"Keeper's DSR is configured. Existing DS-Proxy found at: {self.user_proxy.address.address}")
    
    def dsr_add(self, gas_price):
        # Adding Dai to the DSR
        dai_balance = self.get_dai_balance()
        if dai_balance > Wad(0):
            self.logger.info("Adding Dai balance to the DSR")
            self.dsr.join(dai_balance, self.user_proxy).transact(gas_price=gas_price)
            self.log_balances()

    def dsr_withdraw(self, gas_price, id):
        '''withdraw vat_targer dai from dsr'''

        amt = Wad(self.add_tab())

        if id in self.auc_withdraw.keys(): #prevent new withdraws after bidding
            return False

        if not self.get_dsr_balance() > Wad(0):
            self.logger.debug(f"No Dai in the DSR")
            return False
        
        elif amt <= self.get_vat_balance():
            vat_b = self.get_vat_balance()
            self.logger.debug(f"vat balance = {vat_b}")
            self.logger.debug(f"Enough Dai in the Vat")
            return False

        else:
            max_add = self.vat_target - self.get_vat_balance()
            need_to_bid = amt - self.get_vat_balance()
            if need_to_bid > max_add:
                tot = max_add       
            if need_to_bid > self.get_dsr_balance():
                tot = self.get_dsr_balance()          
            else:
                tot = need_to_bid         
            if tot < Wad.from_number(.001): #avoid withdraw due to rounding errors
                return False
            self.logger.info(f"Withdrawing {tot} Dai from DSR")
            self.dsr.exit(tot, self.user_proxy).transact(gas_price=gas_price)
            self.auc_withdraw[id] = True
            time.sleep(2)
            self.log_balances()
            return True
    
    def vat_withdraw(self, gas_price, vat_dai_balance):
        self.logger.info(f"Exiting {round(vat_dai_balance.__float__(), 3)} Dai from the Vat to deposit in the DSR")
        self.dss.dai_adapter.exit(self.our_address, vat_dai_balance).transact(gas_price=gas_price)
        time.sleep(2)
        self.log_balances()
    
    def remove_auction (self,id):
        if id in self.auction_tab.keys():
            del self.auction_tab[id]
        if id in self.bid_checker.keys():
            del self.bid_checker[id]
    
    
        





