FROM python:3.6.8-alpine

RUN apk update&&apk --no-cache add --virtual build-dependencies build-base gcc wget git&&mkdir /keeper&&cd /keeper&&git clone https://github.com/makerdao/auction-keeper.git &&cd auction-keeper&&git submodule update --init --recursive&&pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple $(cat requirements.txt $(find lib -name requirements.txt | sort) | sort | uniq | sed 's/ *== */==/g') virtualenv&&chown -R keeper.keeper /keeper&&apk del build-dependencies && rm -rf /var/cache/apk/*

WORKDIR /keeper/auction-keeper

RUN rm -rf _virtualenv&&virtualenv --system-site-packages _virtualenv&&sh _virtualenv/bin/activate

ENTRYPOINT ["bin/auction-keeper"]
