import sys
import asyncio

class WorkQueue():
    """ Implements an asynchronous work queue, spawning a number of worker tasks
        to apply a given processing function to all enqueued payloads. 
    """

    def __init__(self, processing_func, max_queue_size = 1000, workers = 4):
        self._processing_func = processing_func
        self._max_queue_size = max_queue_size
        self._workers = workers
        self._worker_tasks = []

        self._queue = asyncio.Queue(maxsize= max_queue_size)
    
        self._running = False


    async def _work(self, worker_id):
        """ Processing loop of a worker.
        """

        while self._running:
            try:
                (item, future) = await self._queue.get()
                
                result = await self._processing_func(item)
                future.set_result(result)
                self._queue.task_done()

            # Catch Cancelled exceptions to avoid forwarding them to future.set_exception()
            except asyncio.CancelledError:
                raise

            except BaseException as e:
                future.set_exception(e)
                self._queue.task_done()
         

    def is_running(self):
        """ Returns True if the workers are currently running. """

        return self._running


    async def join(self):
        """ Waits until all payloads in the queue have been processed. """

        return await self._queue.join()


    def start(self):
        """ Starts all workers. """

        if self._running:
            return

        self._running = True

        for i in range(self._workers):
            task = asyncio.get_event_loop().create_task(self._work(i))
            self._worker_tasks.append(task)


    async def stop(self):
        """ Stops all workers. """

        self._running = False
        for task in self._worker_tasks:
            task.cancel()


    async def enqueue(self, payload):
        """ Enqueues a new payload to be processed.
            Will wait if the queue is full until the payload can enter the queue.
            Returns a Future that can later be awaited to watch for processing completion.
        """

        future = asyncio.get_event_loop().create_future()
        await self._queue.put((payload, future))

        # Do not await here! The client will await when it wants to
        return future 


