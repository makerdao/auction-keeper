#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


# Create a few undercollateralized CDPs
for run in {0..3}
do
    python3 tests/manual/create_unsafe_cdp.py
    python3 tests/manual/print.py
    sleep 1
done


# Create a transaction every 13 seconds to simulate behavior on a real network
while true
do
    # Just a simple transaction
    python3 tests/manual/purchase_dai.py 0.01 > /dev/null
    # Shows changes in debt
    python3 tests/manual/print.py
    # Waits for a mainnet-like block interval
    sleep 13
done

popd > /dev/null