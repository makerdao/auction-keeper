#!/bin/bash

#./ganache.sh &>/dev/null &
#sleep 5

# Start the docker image and wait for parity to initialize
pushd ./lib/pymaker
docker-compose up -d
sleep 2
popd

PYTHONPATH=$PYTHONPATH:./lib/pymaker py.test --cov=auction_keeper --cov-report=term --cov-append tests/ $@

#kill $(lsof -t -i tcp:8555)
#sleep 1

echo Stopping container
pushd ./lib/pymaker
docker-compose down
popd
