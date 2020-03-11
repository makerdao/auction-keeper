#!/bin/bash

# Pull the docker image
docker pull makerdao/testchain-pymaker:unit-testing

# Start the docker image and wait for parity to initialize
pushd ./lib/pymaker
docker-compose up -d
sleep 2
popd

PYTHONPATH=$PYTHONPATH:./lib/pymaker py.test --cov=auction_keeper --cov-report=term --cov-append tests/ --log-date-format="%H:%M:%S" $@
TEST_RESULT=$?

echo Stopping container
pushd ./lib/pymaker
docker-compose down
popd

exit $TEST_RESULT

