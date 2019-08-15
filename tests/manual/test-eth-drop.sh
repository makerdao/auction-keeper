#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


while true
do
    # Drops the price of ETH by 1 Dai every execution
    python3 tests/manual/create_unsafe_cdp.py
    # Shows changes in debt
    python3 tests/manual/print.py
    sleep 13
done

popd > /dev/null
