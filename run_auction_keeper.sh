#!/bin/bash

docker run -it \
	-v <KEYSTORE DIR>:/keystore \
	reflexer/auction-keeper \
        --rpc-uri <ETH_RPC_URL> \
        --eth-from <KEEPER ADDRESS> \
        --eth-key "key_file=/keystore/<KEYSTORE FILE>" \
        --safe-engine-system-coin-target ALL \
        --block-check-interval 1 \
        --bid-check-interval 4 \
        --graph-endpoints https://api.thegraph.com/subgraphs/name/reflexer-labs/prai-mainnet,https://subgraph.reflexer.finance/subgraphs/name/reflexer-labs/rai
