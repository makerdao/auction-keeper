#!/usr/bin/env python
import sys
import json
import random

max_price = float(sys.argv[1]) if len(sys.argv) > 1 else 1000

for line in sys.stdin:
    signal = json.loads(line)
    auction_id = int(signal['id'])

    random.seed(a=auction_id)
    price = max_price * random.random()

    stance = {'price': price}
    print(json.dumps(stance), flush=True)
