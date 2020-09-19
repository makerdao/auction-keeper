#!/bin/bash
dir="$(dirname "$0")"


# Amount of collateral passed as parameter
let "collateral = ${1:-1}"

while true
do
    # Random amount of system coin between 77 and 92
    let "debt = $((RANDOM%15+77)) * $collateral"
    echo Creating SAFE with $collateral collateral and drawing $debt system coin
    ./create-safe.sh $collateral $debt
    mcd -C testnet --ilk=ETH-C drip > /dev/null
    sleep 13
done
