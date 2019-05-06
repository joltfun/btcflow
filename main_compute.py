# Program entrypoint to compute estimates.

import json
import base64
import time
import sys
import os
import asyncio
import pymongo

import txdb
import flow
import utils
import bitcoind
import mongodb_client
import constants


bitcoin_client = bitcoind.BitcoindClient.from_env_variables()


### Database collections ###
db = mongodb_client.load_from_env_variables()
db_txlog = txdb.DbTxLog(db)
db_summaries = txdb.DbTxSummary(bitcoin_client, db)
db_history = txdb.DbHistory(db)


async def load_flow_from_db(seconds):
    """ Computes flows over the last *seconds* of recorded
        transactions.

        Returns a flow.FeeBuckets object in WU/minute.
    """

    print("Load flows over the last " + str(seconds / 60.0 / 60) + " hours...")
    
    results = []
    async for i in db_txlog.fetch(seconds):
        results.append(i)

    print("Got " + str(len(results)) + " transactions from DB")

    txids = list(map(lambda x: x.txid, results))
    
    o = await make_feebuckets_from_txids(txids, log=True)
  
    o.divide(seconds / 60)

    return o


async def make_feebuckets_from_txids(list_txid, log=False):
    """ Returns a flow.FeeBuckets object holding the sum of all
        the weight of transactions from a list of txid's.  
    """
    output = flow.FeeBuckets()
   
    # Load transaction summaries
    summaries = await db_summaries.process(list_txid)
    print("Got summaries:", len(summaries))

    # Add the weight of each tx to the relevant bucket
    for txid in list_txid:
        if txid not in summaries:
            print("Summary not found", txid)
            continue

        tx_summary = summaries[txid]
        if tx_summary == None:
            continue 
        
        fees = tx_summary.inputs - tx_summary.outputs
        weight = tx_summary.weight

        fee_rate = flow.to_fee_rate(fees, weight)

        output[fee_rate] += weight 
        
    return output



async def load_mempool():
    """ Returns a flow.FeeBuckets object holding the sum of all
        the weight of transactions currently in the mempool. 
    """

    print("Load mempool ...")
    mempool = await bitcoin_client.get_raw_mempool()

    return await make_feebuckets_from_txids(mempool)

async def main():
    start_time = time.time()

    # Delete old transactions
    max_age_seconds = max(constants.TARGETS_MINUTE) * 60 * constants.FLOW_TIMESPAN_MULTIPLIER * 2
    print("Trim transactions older than " + str(max_age_seconds / 60 / 60 / 24) + " days")
    trimmed_count = await db_txlog.trim(max_age_seconds)
    print("Trimmed tx count:", trimmed_count)

    
    # Load flows that will be used for each confirmation window
    # TODO: smarter flow loading to avoid refetching the same data from the DB multiple times
    buckets_flow = {}
    for minutes in constants.TARGETS_MINUTE:
        buckets_flow[minutes] = await load_flow_from_db(minutes * 60 * constants.FLOW_TIMESPAN_MULTIPLIER)

    buckets_mempool = await load_mempool()

    estimates = flow.compute_estimates(buckets_mempool, buckets_flow, constants.TARGETS_MINUTE)
    
    output = {
        "timestamp": int(time.time()),
        "estimates": estimates,
        "flow": {(k * constants.FLOW_TIMESPAN_MULTIPLIER): buckets_flow[k]._buckets for k in buckets_flow},
        "mempool": buckets_mempool._buckets
    }
    output_json = json.dumps(output)

    print("Output:", output)

    with open(os.getenv("ESTIMATES_OUTPUT_PATH"), "w") as f:
        f.write(output_json)

    await db_history.insert(output)

    end_time = time.time()
    print("Processing time: " + str(int(end_time - start_time)) + " seconds")

    await bitcoin_client.close()
    print("Bitcoin connection closed")


asyncio.get_event_loop().run_until_complete(main())
