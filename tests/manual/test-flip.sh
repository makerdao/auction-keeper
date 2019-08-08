#!/bin/bash
pushd ../..
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


# Create a few undercollateralized CDPs
for run in {0..4}
do
    python3 tests/manual/create_unsafe_cdp.py
    sleep 3
done


# Create a transaction every 13 seconds to simulate behavior on a real network
while true
do
    # Just a simple transaction
    python3 tests/manual/purchase_dai.py 0.01
    # Dumps auction details for debugging
    python3 tests/manual/dump_auction_info.py
    # Waits for a mainnet-like block interval
    echo
    sleep 13
done

popd