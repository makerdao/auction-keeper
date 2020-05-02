#!/usr/bin/env python3
import json
import time
import requests
import sys
import os
import logging
import signal


class Bid_Price():
    logger = logging.getLogger()

    def __init__(self):
        self.our_price = 0
        self.ETHUSD = None
        self.DAIUSDC = None
        self.logname = "logger" + str(os.getpid()) + ".txt"

    @staticmethod   
    def get_quote (url, parameter=None):
        try:
            response = requests.get(url, params=parameter)
            if response.status_code == 200:
                response = response.json()
            else:
                response = False
        except Exception as e:
            response = False
            print(e)
        return (response)

    def get_coinbase(self):
        '''get selected coinbase quotes'''
        base = "https://api.pro.coinbase.com"
        parameters = ['/products/ETH-USD/ticker', '/products/DAI-USDC/ticker']
        attrs = ['ETHUSD', 'DAIUSDC']
        for num, param in enumerate(parameters):
            url = base+param
            response = self.get_quote(url)
            if response:
                try:
                    setattr(self, attrs[num], float(response['bid']))
                except:
                    return False
            else:
                return False
        return True

    def get_auction_status(self):
        try:
            line = sys.stdin.readline()
            self.status = json.loads(line)
            self.time_left = self.status['end'] - time.time()
            self.lot_size = float(self.status['lot'])
            self.current_bid = float(self.status['price'])
            self.bid_increment = float(self.status['beg'])
            self.guy = self.status['guy']
            self.tic = self.status['tic']

        except Exception as e:
            print(e, file=sys.stderr)
    

    def calc_bid(self):
        try:
            eth_price_in_dai = self.ETHUSD / self.DAIUSDC
            self.our_price = eth_price_in_dai
            return True
        except Exception as e:
            self.our_price = None
            print(e, file=sys.stderr)
            return False
    

    def check_gasprice(self):
        url = "https://ethgasstation.info/json/ethgasAPI.json"
        response = self.get_quote(url)
        if response:
            try:
                gp = (response['fast']+2)*1e8
            except:
                gp = False
        else:
            gp = False
        return gp
    
    def make_output(self, make_bid, gp):

        if make_bid and gp:
            out = {
                'price' : str(self.our_price),
                'gasPrice' : gp
            }        
        elif make_bid:
            out = {
                'price' : str(self.our_price)
            }
        else:
            out = None
        
        return out

def main():
    bid = Bid_Price()
    while True:
        try:
            bid.get_auction_status()
            make_bid = bid.get_coinbase()
            if make_bid:
                make_bid = bid.calc_bid()
            gp = bid.check_gasprice()
            out_dict = bid.make_output(make_bid, gp)
            if out_dict:
                print(json.dumps(out_dict))
                sys.stdout.flush()
            
            with open(bid.logname, 'a') as log:
                print (bid.status, file=log)
                print(out_dict, file=log)
                print("ETH/DAI Price: " + str(bid.our_price), file=log)
                print ("Time Left(m): " + str(round((bid.time_left/60),1)), file=log)
                current_time = time.strftime("%a, %d %b %Y %H:%M:%S")
                print ("Current Time: " + current_time, file=log)
            time.sleep(10)
        except:
            sys.exit()

if __name__ == "__main__":
    main()