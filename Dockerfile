FROM python:3.6.8

RUN mkdir /keeper&&groupadd keeper&&useradd -d /keeper -g keeper keeper&&cd /keeper&&git clone https://github.com/makerdao/auction-keeper.git &&cd auction-keeper&&git submodule update --init --recursive&&pip install --no-cache-dir $(cat requirements.txt $(find lib -name requirements.txt | sort) | sort | uniq | sed 's/ *== */==/g') virtualenv&&chown -R keeper.keeper /keeper


USER keeper
WORKDIR /keeper/auction-keeper

RUN rm -rf _virtualenv&&virtualenv --system-site-packages _virtualenv&&sh _virtualenv/bin/activate

ENTRYPOINT ["bin/auction-keeper"]
