#!/bin/bash
source ../../_virtualenv/bin/activate
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pyflex:$dir/lib/pygasprice-client/
python3 tests/testchain/print.py $@
popd > /dev/null
