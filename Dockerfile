FROM python:3.6.6

RUN groupadd -r keeper && useradd --no-log-init -r -g keeper keeper

COPY bin /opt/keeper/auction-keeper/bin
COPY auction_keeper /opt/keeper/auction-keeper/auction_keeper
COPY lib /opt/keeper/auction-keeper/lib
COPY requirements.txt /opt/keeper/auction-keeper/requirements.txt

WORKDIR /opt/keeper/auction-keeper
RUN pip3 install -r requirements.txt
WORKDIR /opt/keeper/auction-keeper/bin

USER keeper