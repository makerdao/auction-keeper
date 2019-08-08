#!/bin/bash
pushd ../..
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker

# Creates a CDP using another account and transfers the Dai to the keeper account
python3 tests/manual/purchase_dai.py 500