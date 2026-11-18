"""
main.py
CLI entry point. Handles arguments and traps SIGINT (Ctrl+C).
"""

import argparse
import signal
import sys
from server import WebServer


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Threaded OS Web Server with Fixed Pool"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind (default: 8080)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of worker threads (default: 4)",
    )
    parser.add_argument(
        "--dir",
        default="public",
        help="Directory to serve (default: public)",
    )
    args = parser.parse_args()

    server = WebServer(
        port=args.port, workers=args.workers, web_root=args.dir
    )

    def handle_sigint(sig, frame):
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    server.start()


if __name__ == "__main__":
    main()