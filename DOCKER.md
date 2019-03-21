#  Build and run auction keeper as Docker image
## Prerequisite:
- docker installed: https://docs.docker.com/install/
- docker-compose: https://docs.docker.com/compose/install/
- Git

## Installation
Clone project and install required third-party packages:
```
git clone https://github.com/makerdao/auction-keeper.git
cd auction-keeper
git submodule update --init --recursive
```

## Build and run:
In `auction-keeper` directory:
- create `hush` directory and add keystore (`auction.json`) and password (`auction.pass`) files
- create `model` directory containing model file (`model.sh`)
- create `.env` file with following format:
```
RPC_HOST={RPC_NODE_IP_OR_HOST_HERE}
RPC_PORT={RPC_NODE_PORT_HERE}
ETH_FROM={ETH_ADDRESS_HERE}
FLIPPER_ADDRESS={FLIPPER_ADDRESS_HERE}
FLOPPER_ADDRESS={FLOPPER_ADDRESS_HERE}
FLAPPER_ADDRESS={FLAPPER_ADDRESS_HERE}
CAT_ADDRESS={CAT_ADDRESS}
VOW_ADDRESS={VOW_ADDRESS}
```
- run `docker-compose build`
- start individual auction_keepers as:
```
docker-compose up flipper_auction
docker-compose up flopper_auction
docker-compose up flapper_auction
```
or all keepers as
```
docker-compose up
````

