# Program entrypoint for logging transactions going through the mempool of a Bitcoind node.

# TODO: Get rawtx data and parse the transaction summaries from there (avoids polling Bitcoind later)
# TODO: Detect double-spent/RBF-ed transactions.

import binascii
import asyncio
import zmq
import zmq.asyncio
import signal
import struct
import sys
import os
import time
import socket

import bitcoind
import txdb
import mongodb_client

# It seems like hostname resolution doesn't work if we let the ZMQ lib resolve it,
# so resolve it ourselves
BITCOIN_HOST =  socket.gethostbyname(os.getenv("BITCOIN_HOST", "127.0.0.1"))
BITCOIN_ZMQ_PORT = int(os.getenv("BITCOIN_ZMQ_PORT"))
ZMQ_URL = "tcp://" + BITCOIN_HOST + ":" + str(BITCOIN_ZMQ_PORT)

bitcoin_client = bitcoind.BitcoindClient.from_env_variables()
db = mongodb_client.load_from_env_variables()
db_txlog = txdb.DbTxLog(db)



async def process_tx_notification(txid):
    """ Logs the given txid """

    # Do not block the main loop if there's an issue, just log
    try:
        await db_txlog.insert(txid)
    except Exception as e:
        print("Exception in process_tx_notification", e)


class ZMQHandler():
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.zmqContext = zmq.asyncio.Context()

        self.zmqSubSocket = self.zmqContext.socket(zmq.SUB)
        self.zmqSubSocket.setsockopt(zmq.RCVHWM, 0)
        #self.zmqSubSocket.setsockopt_string(zmq.SUBSCRIBE, "hashblock")
        self.zmqSubSocket.setsockopt_string(zmq.SUBSCRIBE, "hashtx")
        #self.zmqSubSocket.setsockopt_string(zmq.SUBSCRIBE, "rawblock")
        #self.zmqSubSocket.setsockopt_string(zmq.SUBSCRIBE, "rawtx")

        print("Open ZMQ socket on", ZMQ_URL)
        self.zmqSubSocket.connect(ZMQ_URL)

    async def load_from_mempool(self):
        """ Polls Bitcoind's mempool and logs each transaction sitting there. """

        mempool = await bitcoin_client.get_raw_mempool(True)
        batch = []
        for txid in mempool:
            time = mempool[txid]["time"]
            #print(txid, time)
            batch.append( txdb.RecordTransactionLog(txid, time) )

        await db_txlog.insert_bulk(batch)

        print("- Loaded transactions from mempool:", len(batch))

        # Call ourselves again sometime later.
        # This is to periodically poll the mempool state.
        # ZMQ should be considered as "unreliable" and might miss some notifications.
        self.loop.call_later(60, lambda: self.loop.create_task(self.load_from_mempool()))
    

    async def handle(self) :
        """ Handles the next ZMQ message. """

        msg = await self.zmqSubSocket.recv_multipart()
        topic = msg[0]
        body = msg[1]
        sequence = "Unknown"

        if len(msg[-1]) == 4:
          msgSequence = struct.unpack('<I', msg[-1])[-1]
          sequence = str(msgSequence)

        if topic == b"hashtx":
            txid = body.hex()
            print('- tx ('+sequence+') ', txid)
            
            asyncio.create_task(process_tx_notification(txid))

        # schedule ourselves to receive the next message
        asyncio.ensure_future(self.handle())

    def start(self):
        self.loop.add_signal_handler(signal.SIGINT, self.stop)
        self.loop.create_task(self.load_from_mempool())
        self.loop.create_task(self.handle())
        self.loop.run_forever()

    def stop(self):
        self.loop.stop()
        self.zmqContext.destroy()

daemon = ZMQHandler()
daemon.start()
