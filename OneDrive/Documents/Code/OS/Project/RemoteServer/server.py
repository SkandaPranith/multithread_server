"""
server.py
The network listener and Producer. Binds socket on 0.0.0.0, accepts client
connections, and deposits connection jobs into the thread pool.
"""

import os
import socket
from http_handler import handle_request
from thread_pool import BoundedThreadPool


class WebServer:

    def __init__(self, host="0.0.0.0", port=8080, workers=4, web_root="public"):
        self.host = host
        self.port = port
        self.web_root = os.path.realpath(web_root)
        os.makedirs(self.web_root, exist_ok=True)

        self.pool = BoundedThreadPool(num_workers=workers, max_queue_size=32)
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.running = False

    def start(self):
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(128)
        # Timeout allows Windows OS to periodically unblock accept() and catch Ctrl+C
        self.server_sock.settimeout(1.0)
        self.running = True

        print("=" * 60)
        print(f"[*] Mini-Apache OS Web Server Running")
        print(f"[*] Local access:    http://127.0.0.1:{self.port}")
        print(
            f"[*] Worker threads:  {self.pool.num_workers} (Fixed Thread Pool)"
        )
        print(f"[*] Serving files:   {self.web_root}")
        print("=" * 60)

        try:
            while self.running:
                try:
                    client_sock, client_addr = self.server_sock.accept()
                except TimeoutError:
                    continue  # Ticks every 1s so Ctrl+C is caught immediately!
                except OSError:
                    break  # Socket closed during shutdown

                # Package the task for worker execution
                task = (
                    lambda s=client_sock, a=client_addr: handle_request(
                        s, a, self.web_root
                    ),
                    client_sock,
                    client_addr,
                )

                # Producer enqueues task; blocks if capacity exceeded
                if not self.pool.submit(task):
                    client_sock.close()

        finally:
            self.stop()

    def stop(self):
        if not self.running:
            return
        print("\n[*] Shutting down server...")
        self.running = False
        try:
            self.server_sock.close()
        except OSError:
            pass
        self.pool.shutdown()
        print("[*] Server shutdown complete.")