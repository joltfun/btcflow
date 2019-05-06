# Contains database record objects and subsystems
# providing access to database collections

import time
import os
import datetime
import json
import pymongo
import asyncio

import constants

### Database records

class RecordTransactionLog:
    """ Record indicating when a Txid was first seen:
    
        txid      -- transaction id
        timestamp -- Unix timestamp (seconds since 1970-01-01)
    """

    def __init__(self, txid, timestamp):
        self.txid = txid 
        self.timestamp = timestamp


class RecordTransactionSummary():
    """ Record providing a simplified summary of some transaction:
        txid    -- transaction id
        weight  -- the size of the transaction in Weight-Units
        inputs  -- sum of the inputs in satoshis
        outputs -- sum of the outputs in satoshis
    """

    def __init__(self, txid, weight, inputs, outputs):
        self.txid = str(txid)
        self.weight = int(weight)
        self.inputs = int(inputs)
        self.outputs = int(outputs)
    
    def get_fees(self):
        """ Total fees paid out to the miner in satoshis. """
        return self.inputs - self.outputs

    def to_document(self):
        """ Formats the record to be inserted in MongoDB. """

        return {
            "_id": self.txid,
            "_cache_time":  datetime.datetime.utcnow(), # to enable TTL
            "weight": self.weight, 
            "inputs": self.inputs, 
            "outputs": self.outputs
        }


### Database collections subsystems

class DbTxLog:
    """ Collection of RecordTransactionLog. """

    def __init__(self, mongo_db):
        self._collection = mongo_db["tx_log"]
        self._collection.create_index("time")

    async def trim(self, max_age_seconds):
        """ Removes older transactions 
        """
        threshold = int(time.time()) - max_age_seconds
        result = await self._collection.delete_many( {"time": {"$lt": threshold}} )
        return result.deleted_count

    async def insert(self, txid, timestamp= None):
        if timestamp == None:
            timestamp = int(time.time())

        await self.insert_bulk([RecordTransactionLog(txid, timestamp)])

    async def insert_bulk(self, list_of_records):
        """ Inserts a list of multiple RecordTransactionLog. """

        # Map all records to upsert operations and update only if we got the earliest timestamp for each tx
        write_ops = [
            pymongo.UpdateOne({'_id': i.txid}, {'$min': {'time': i.timestamp}}, upsert= True) 
            for i in list_of_records
        ]

        await self._collection.bulk_write(write_ops, ordered= False)

    async def fetch(self, max_age):
        """ Iterates through records that are no older than *max_age* seconds. """

        now = int(time.time())
        threshold = now - max_age
        cursor = self._collection.find({'time': {'$gte': threshold}})
        async for doc in cursor:
            yield RecordTransactionLog(doc['_id'], doc['time'])





class DbTxSummary():
    """ Collection of RecordTransactionSummary.
        This is a cache collection, records expire automatically after 2 days.
    """

    def __init__(self, bitcoin_client, mongo_db):
        self._bitcoind = bitcoin_client
        self._collection = mongo_db["tx_summary"]
        self._collection.create_index("_cache_time", expireAfterSeconds= 60 * 60 * 24 * 2)

        # TODO: Replace the in-memory cache using a LRU
        #self._summary_cache = {}

    async def _compute_input_sum(self, tx):
        """ Given a transaction dict, fetches all of its inputs and
            returns the sum (in satoshis). 
        """

        # Find all input transaction ids
        input_txids = map(lambda x: x["txid"], tx["vin"])

        # Now load those
        #TODO: in parallel
        input_txs= {}
        for iid in input_txids:
            input_txs[iid] = await self._bitcoind.get_raw_transaction(iid, True)

        # Now we can compute the input sum
        input_sum = 0
        for input in tx["vin"]:
            input_sum += int(constants.COIN * input_txs[input["txid"]]["vout"][input["vout"]]["value"])

        return input_sum

    def _compute_output_sum(self, tx):
        """ Given a transaction dict, returns the sum of all
            of its outputs (in satoshis.)
        """

        output_sum = 0
        for vout in tx["vout"]:
            output_sum += int(constants.COIN * vout["value"])

        return output_sum

    def _is_coinbase(self, tx):
        return "coinbase" in tx["vin"][0]

    async def _compute_tx_summary(self, txid):
        """ Given a transaction id, fetches all the necessary data
            and returns a RecordTransactionSummary.
        """

        #if txid in self._summary_cache:
        #    return self._summary_cache[txid]

        tx = await self._bitcoind.get_raw_transaction(txid, True)

        if tx == None:
            return None

        outputs = self._compute_output_sum(tx)
        inputs  = outputs if self._is_coinbase(tx) else (await self._compute_input_sum(tx))

        result = RecordTransactionSummary(txid, tx["weight"], inputs, outputs)
        #self._summary_cache[txid] = result
        return result

    
    async def process(self, txid_list):
        """ Given a list of txid's, returns a list
            of RecordTransactionSummary() objects.
        """

        # TODO: Refactor: method too big, split this in smaller methods.

        # TODO: Even better refactoring to avoid having to pull thousands of
        # summaries from the DB over and over again. 
        # One idea would be to compute "time segment summaries", that contain an 
        # overview of what happened during some period of time.

        records = {}

        # Load summaries from the cache:
        print("DbTxSummary: fetch transactions in cache:", len(txid_list))
        
        queue_ids_to_load = list(txid_list) 
        while len(queue_ids_to_load) > 0:
              
            cursor = self._collection.find({"_id": {"$in": queue_ids_to_load[:100000]}})
            queue_ids_to_load = queue_ids_to_load[100000:]

            async for doc in cursor:
                records[doc["_id"]] = RecordTransactionSummary( doc["_id"], doc["weight"], doc["inputs"], doc["outputs"] )

        print("DbTxSummary: transactions found in cache:", len(records))



        # Construct missing summaries that weren't found in the cache:
  
        async def construct_tx_summary(txid):
            """ Compute a summary and insert in into the DB cache. """

            tx_summary = await self._compute_tx_summary(txid)
            records[txid] = tx_summary 
            
            if tx_summary != None:
                await self._collection.insert_one(tx_summary.to_document())
            return (txid, tx_summary)

        count_constructed_summaries = 0
        pending = []

        def any_done():
            m = map(lambda x: x.done(), pending)
            return any(m)

        txid_to_construct = [txid for txid in txid_list if not txid in records]

        print("DbTxSummary: will construct transactions:", len(txid_to_construct))

        # Poll bitcoind for missing summaries
        for txid in txid_to_construct:
            count_constructed_summaries+= 1
            
            # TODO: Maybe rewrite this as a Queue?
            # If there's too many pending tasks, block until at least one is done
            if len(pending) > 1000:
                while not any_done():
                    await asyncio.sleep(0.1)

                pending = [t for t in pending if not t.done()]

            pending.append( asyncio.create_task( construct_tx_summary(txid) ))

        await asyncio.gather(*pending)

        print("DbTxSummary: constructed: ", count_constructed_summaries)
        print("DbTxSummary: done")

        return records


class DbHistory():
    """ Collects historical estimates. """

    def __init__(self, mongo_db):
        self._collection = mongo_db["history"]
        self._collection.create_index("timestamp")

    async def insert(self, output):
        """ output -- the estimates output to save """

        output_json = json.dumps(output)
        doc = {"time": output["timestamp"], "json": output_json}

        await self._collection.insert_one(doc)


