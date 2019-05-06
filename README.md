# Btcflow
Mempool and flow-based Bitcoin fee estimator.

Developed by [/u/bitbug42](https://www.reddit.com/user/bitbug42) as part of the project [Bitcoiner.live](https://bitcoiner.live/)  
Tips [through BTCPay (on-chain or Lightning)](https://pay.joltfun.com/apps/2F6y2o2fUUW1fUGj9p26CXV4qxSF/pos)

## Requirements

* A synced Bitcoind full node
* A MongoDB database.

**! WARNING !** MongoDB authentication is currently not implemented. Use only on a local MongoDB instance that is not accessible to external networks.

## Environment variables

**Mandatory**

* `FLOW_MODE`: "LOG" or "COMPUTE" to start the Docker container in logging mode or computing mode (calculating estimates).
* `ESTIMATES_OUTPUT_PATH`: where the JSON file containing estimates will be written (COMPUTE mode only)
* `BITCOIN_ZMQ_PORT`: ZMQ port publishing `hashtx` notifications (LOG mode only)

**Optional**

* `BITCOIN_HOST`: default="127.0.0.1"
* `BITCOIN_PORT`: default="8332"
* `BITCOIN_USER`: default="kek"
* `BITCOIN_PASS`: default=""
* `MONGODB_HOST`: default="127.0.0.1"
* `MONGODB_PORT`: default="27017"
* `MONGODB_DATABASE`: default="txdb"


## Building

`docker build -t btcflow .`

## Running the logger

`docker run -e FLOW_MODE=LOG -e BITCOIN_ZMQ_PORT=xxxxx btcflow`

The logger will connect to the specified Bitcoind node through ZMQ to get real time transaction notifications as well as through the regular RPC interface to take periodic mempool snapshots.

Your Bitcoind node must have ZMQ notifications enabled: `zmqpubhashtx=tcp://IP:PORT`.

Each new transaction will be logged into a MongoDB collection alongside a timestamp of when it was first seen entering the mempool.

## Running the estimator

`docker run -e FLOW_MODE=COMPUTE -e ESTIMATES_OUTPUT_PATH=estimates.json btcflow`

The container will connect to the MongoDB database, fetch the log of transactions, load transactions and the latest mempool from Bitcoind, compute estimates and store the result to the requested file.

It will then wait 60 seconds and start again in a loop.

## Output file format

A JSON object containing the following nested properties:

* `mempool[feerate]` = Weight-Units currently in the mempool at `feerate`
* `flow[timespan][feerate]` = Weight-Units per minute entering the mempool over the last `timespan` minutes at `feerate`
* `estimates.by_minute[timespan][probability]` =  recommended fee-rate to have at least `probability` chances to be confirmed within `timespan` minutes

All fee-rates are in satoshis-per-vbyte.  
All timespans are in minutes.  
Probabilities are expressed between 0.0 and 1.0.

