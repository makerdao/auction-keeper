#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pyflex

# Amount of collateral passed as parameter
let "collateral = ${1:-5}"
# Chooses collateral type
COLLATERAL_TYPE=${2:-ETH-C}

while true
do
    # Drops the price of collateral by 1 system coin every execution
    python3 tests/manual/create_almost_risky_safe.py ${collateral} ${COLLATERAL_TYPE}
    # Shows changes in debt
    python3 tests/manual/print.py
    sleep 30
done

popd > /dev/null
