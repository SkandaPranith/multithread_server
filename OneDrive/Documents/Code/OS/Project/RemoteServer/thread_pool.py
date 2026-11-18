"""
thread_pool.py
Implements a bounded Producer-Consumer thread pool using raw OS synchronization
primitives: Mutex (threading.Lock) and Condition Variables (threading.Condition).
"""

import threading
from collections import deque


class BoundedThreadPool:

    def __init__(self, num_workers=4, max_queue_size=16):
        self.num_workers = num_workers
        self.max_queue_size = max_queue_size
        self.tasks = deque()

        # OS Mutual Exclusion lock
        self.lock = threading.Lock()

        # Condition variables bound to the lock (signaling without busy-waiting)
        self.not_empty = threading.Condition(self.lock)
        self.not_full = threading.Condition(self.lock)

        self.is_shutdown = False
        self.workers = []

        # Spawn fixed pool of worker threads (Consumers)
        for i in range(num_workers):
            t = threading.Thread(
                target=self._worker_loop, name=f"Worker-{i+1}", daemon=True
            )
            t.start()
            self.workers.append(t)

    def submit(self, task):
        """Producer method: places connection task into the queue.

        Blocks if queue capacity is exceeded (prevents memory exhaustion).
        """
        with self.lock:
            # While queue is full, wait for consumers to create space
            while len(self.tasks) >= self.max_queue_size and not self.is_shutdown:
                self.not_full.wait()

            if self.is_shutdown:
                return False

            self.tasks.append(task)
            # Wake up one sleeping consumer thread
            self.not_empty.notify()
            return True

    def _worker_loop(self):
        """Consumer method: workers wait for jobs and execute them."""
        while True:
            with self.lock:
                # Sleep at 0% CPU until a task arrives
                while not self.tasks and not self.is_shutdown:
                    self.not_empty.wait()

                if self.is_shutdown and not self.tasks:
                    break

                handler_func, client_sock, client_addr = self.tasks.popleft()
                # Signal the producer that a slot has freed up
                self.not_full.notify()

            # Execute work OUTSIDE the lock so other workers run in parallel
            try:
                handler_func(client_sock, client_addr)
            except Exception as e:
                print(
                    f"[{threading.current_thread().name}] Handler error: {e}"
                )
            finally:
                try:
                    client_sock.close()
                except OSError:
                    pass

    def shutdown(self):
        """Wakes up all sleeping workers and cleanly joins them."""
        with self.lock:
            self.is_shutdown = True
            self.not_empty.notify_all()
            self.not_full.notify_all()

        for t in self.workers:
            t.join(timeout=2)