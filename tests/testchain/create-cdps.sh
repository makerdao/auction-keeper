#!/bin/bash
dir="$(dirname "$0")"


# Amount of collateral passed as parameter
let "ink = ${1:-1}"

while true
do
    # Random amount of Dai between 77 and 92
    let "art = $((RANDOM%15+77)) * $ink"
    echo Creating CDP with $ink collateral and drawing $art Dai
    ./create-cdp.sh $ink $art
    mcd -C testnet --ilk=ETH-C drip > /dev/null
    sleep 13
done
