#!/bin/sh

PYTHONPATH=$PYTHONPATH:./lib/pymaker py.test --cov=auction_keeper --cov-report=term --cov-append tests/
