#!/bin/bash

CONFIG="testchain-value-fixed-discount-governance-median-multisig"
while getopts :c:f: option
do
case "${option}"
in
c) CONFIG=${OPTARG};;
f) TEST_FILE=${OPTARG};;
esac
done

# Pull the docker image
docker pull reflexer/testchain-pyflex:${CONFIG}

# Start the docker image and wait for parity to initialize
#pushd ./lib/pymaker
pushd ./lib/pyflex
docker-compose -f config/${CONFIG}.yml up -d
sleep 2
popd

PYTHONPATH=$PYTHONPATH:./lib/pymaker:./lib/pygasprice-client:./lib/pyflex py.test -s\
  --cov=auction_keeper --cov-report=term --cov-append \
  --log-format="%(asctime)s %(levelname)s %(message)s" --log-date-format="%H:%M:%S" \
  tests/${TEST_FILE}
TEST_RESULT=$?

echo Stopping container
pushd ./lib/pyflex
docker-compose -f config/${CONFIG}.yml down
popd

exit $TEST_RESULT
