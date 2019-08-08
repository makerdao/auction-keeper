#!/bin/bash
pushd ../..
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


#python3 tests/manual/create_debt.py


# Create a transaction every 13 seconds to simulate behavior on a real network
while true
do
    # Just a simple transaction
    python3 tests/manual/purchase_dai.py 0.01 > /dev/null
    # Shows changes in debt
    python3 tests/manual/create_debt.py --print-only
    # Waits for a mainnet-like block interval
    sleep 13
done

popd