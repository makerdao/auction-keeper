#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker

# Amount of collateral passed as parameter
let "ink = ${1:-5}"
# Chooses collateral type
ILK=${2:-ETH-C}

while true
do
    # Drops the price of collateral by 1 Dai every execution
    python3 tests/manual/create_unsafe_cdp.py ${ink} ${ILK}
    # Shows changes in debt
    python3 tests/manual/print.py
    sleep 30
done

popd > /dev/null
