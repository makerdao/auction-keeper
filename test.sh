#!/bin/bash

# Pull the docker image
docker pull makerdao/testchain-pymaker:unit-testing

# Start the docker image and wait for parity to initialize
pushd ./lib/pymaker
docker-compose up -d
sleep 2
popd

PYTHONPATH=$PYTHONPATH:./lib/pymaker:./lib/pygasprice-client py.test \
  --cov=auction_keeper --cov-report=term --cov-append \
  --log-format="%(asctime)s %(levelname)s %(message)s" --log-date-format="%H:%M:%S" \
  tests/ $@
TEST_RESULT=$?

echo Stopping container
pushd ./lib/pymaker
docker-compose down
popd

exit $TEST_RESULT

