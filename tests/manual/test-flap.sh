#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


python3 tests/manual/create_surplus.py

# Create a transaction every 13 seconds to simulate behavior on a real network
while true
do
    # Just a simple transaction
    python3 tests/manual/mint_mkr.py 0.05 > /dev/null
    # Shows changes in debt
    python3 tests/manual/print.py
    # Waits for a mainnet-like block interval
    sleep 6
done

popd > /dev/null