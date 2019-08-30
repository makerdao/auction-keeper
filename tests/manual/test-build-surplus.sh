#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


while true
do
    # Argument is the amount of collateral to place in the CDP, which impacts the stability fees
    python3 tests/manual/create_surplus.py 100
    # Show change in surplus (joy)
    python3 tests/manual/print.py
    sleep 13
done

popd > /dev/null
