#!/bin/bash

docker run \
	-v /home/ec2-user/keystore:/keystore reflexer/auction-keeper \
	-v /home/ec2-user/models:/models reflexer/auction-keeper \
        --type collateral \
        --collateral-type ETH-A \
        --rpc-host <ETH_RPC_URL> \
        --eth-from <KEEPER_ADDRESS \
        --eth-key "key_file=/keystore/key.json" \
        --model /models/collateral/model.sh \
        --from-block 11000000 \
        --safe-engine-system-coin-target 'ALL' \
        --block-check-interval 5 \
        --graph-endpoints https://api.thegraph.com/subgraphs/name/reflexer-labs/prai-mainnet,https://subgraph.reflexer.finance/subgraphs/name/reflexer-labs/rai
