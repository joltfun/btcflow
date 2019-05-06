# Simple utility to contact bitcoind through HTTP

import os
import sys
import time
import asyncio
import aiohttp
import json
import base64
import http.client

import utils

class BitcoindHttpException(Exception):
    """ Thrown when a Bitcoin RPC request returns an error
    """

    def __init__(self, code, message):
        self.code = code
        self.message = message

class BitcoindClient():
    """ Implements a simple asynchronous client to send
        RPC requests to a bitcoind instance.
    """

    def __init__(self, bitcoin_host, bitcoin_port, bitcoin_user, bitcoin_pass):
        self._bitcoin_host = str(bitcoin_host)
        self._bitcoin_port = int(bitcoin_port)
        self._bitcoin_user = str(bitcoin_user)
        self._bitcoin_pass = str(bitcoin_pass)

        self._url = "http://" + self._bitcoin_host + ":" + str(self._bitcoin_port) + "/"

        # Precompute authentication headers
        auth = "Basic " + base64.b64encode((self._bitcoin_user+":"+self._bitcoin_pass).encode('utf8') ).decode('utf8')
        self._request_headers = {
            "Content-Type": "application/json",
            "Authorization": auth
        }

        self._request_count = 0

        conn = aiohttp.TCPConnector(limit= 8)
        self._session = aiohttp.ClientSession(connector= conn)

        self._queue = utils.WorkQueue(self._process_http, max_queue_size= 10000, workers= 8)
        self._queue.start()

    @staticmethod
    def from_env_variables():
        """ Creates a new instance using environment variables for configuration.
        """

        return BitcoindClient(
            bitcoin_user= os.getenv("BITCOIN_USER", "kek"),
            bitcoin_pass= os.getenv("BITCOIN_PASS", ""),
            bitcoin_host= os.getenv("BITCOIN_HOST", "127.0.0.1"),
            bitcoin_port= int(os.getenv("BITCOIN_PORT", "8332"))
        )

    async def close(self):
        """ Closes all RPC connections and stops all workers.
        """

        await asyncio.gather(
            self._session.close(),
            self._queue.stop()
        )

    async def _enqueue_http(self, method, body):
        """ Submits a RPC request to the work queue to be
            processed later.

            Arguments:
            method -- name of the RPC method to invoke (string)
            body -- Arguments to send to the method (list)
        """ 

        # Awaits: first one until request is enqueued, second one until it gets processed
        return await (await self._queue.enqueue((method, body)))

    async def _process_http(self, payload):
        """ Work queue processing method.
            Sends a request and reads the response.

            Arguments:
            payload -- (method, body) tuple
        """

        (method, body) = payload 

        self._request_count+= 1

        request_json = {
                "jsonrpc": "1.0",
                "id": str(self._request_count), 
                "method": method,
                "params": body
        }

        async with self._session.post(self._url, json= request_json, headers= self._request_headers) as resp:
            try:
                response_txt = await resp.text()
                response_obj = json.loads(response_txt)

            except json.decoder.JSONDecodeError:
                print("Error in JSON decoding:", response_txt) 
                raise

        error = response_obj["error"]

        if error != None:
            raise BitcoindHttpException(error["code"], error["message"])
            
        return response_obj["result"]

    async def get_raw_mempool(self, verbose= False):
        return await self._enqueue_http("getrawmempool", [verbose])

    async def get_raw_transaction(self, txid, verbose):
        """ Fetches a transaction.
            Returns the raw encoding in hexadecimal if verbose=False
            Otherwise returns the JSON decoding as given by Bitcoind.
            Returns None if the transaction cannot be found.
        """

        try:
            return await self._enqueue_http("getrawtransaction", [txid, verbose])
        except BitcoindHttpException as e:
            if e.code == -5: # tx not found
                return None
            else:
                raise e 
