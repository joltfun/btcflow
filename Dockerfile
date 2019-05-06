FROM python

RUN apt-get update
RUN apt-get install -y libzmq3-dev 

RUN pip install pyzmq scipy motor aiohttp

WORKDIR /opt/btcflow

COPY *.py ./
COPY *.sh ./

CMD exec bash entrypoint.sh
