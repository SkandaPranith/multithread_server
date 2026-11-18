"""
http_handler.py
Handles parsing incoming HTTP requests, identifying client devices/browsers,
enforcing path sandboxing, auto-decoding spaces (%20), and streaming media
via HTTP 206 Partial Content (Byte-Range requests) to prevent video stalling.
"""

import os
import threading
from urllib.parse import unquote

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".pdf": "application/pdf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def parse_device_info(user_agent):
    """Parses HTTP User-Agent header to identify device and browser."""
    ua = user_agent.lower()

    if "iphone" in ua:
        device = "iPhone"
    elif "ipad" in ua:
        device = "iPad"
    elif "android" in ua:
        device = "Android Phone"
    elif "windows" in ua:
        device = "Windows PC"
    elif "macintosh" in ua or "mac os" in ua:
        device = "Mac"
    elif "linux" in ua:
        device = "Linux Machine"
    else:
        device = "Client Device"

    if "code/" in ua or "electron" in ua:
        browser = "VS Code Browser"
    elif "edg" in ua:
        browser = "Edge"
    elif "chrome" in ua:
        browser = "Chrome"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "firefox" in ua:
        browser = "Firefox"
    else:
        browser = "WebBrowser"

    return f"{device} [{browser}]"


def resolve_safe_path(base_dir, requested_path):
    """OS Sandboxing: Prevents directory traversal attacks (e.g., ../../Windows).

    Automatically handles spaces and special URL-encoded characters (unquote).
    """
    raw_rel = requested_path.lstrip("/").split("?")[0]
    # Decode URL-encoded characters like %20 into real spaces
    clean_path = unquote(raw_rel)

    if not clean_path or clean_path.endswith("/"):
        clean_path += "index.html"

    full_path = os.path.realpath(os.path.join(base_dir, clean_path))
    real_base = os.path.realpath(base_dir)

    if (
        os.path.commonpath([real_base, full_path]) != real_base
        or not os.path.isfile(full_path)
    ):
        return None

    return full_path


def handle_request(client_sock, client_addr, web_root="public"):
    """Reads HTTP request, handles Byte-Range streaming (HTTP 206), and streams response."""
    worker_id = threading.current_thread().name

    try:
        raw_header = client_sock.recv(4096)
        if not raw_header:
            return

        lines = raw_header.decode("utf-8", errors="ignore").splitlines()
        if not lines:
            return

        parts = lines[0].split()
        if len(parts) < 2:
            return

        method, path = parts[0], parts[1]

        # Parse HTTP headers
        headers = {}
        for line in lines[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.lower()] = v.strip()

        user_agent = headers.get("user-agent", "")
        device_label = parse_device_info(user_agent)
        client_ip = (
            headers.get("x-forwarded-for", client_addr[0]).split(",")[0].strip()
        )

        print(
            f"[{worker_id}] -> {device_label} ({client_ip}) | {method}"
            f" {unquote(path)}"
        )

        if method != "GET":
            client_sock.sendall(
                b"HTTP/1.1 501 Not Implemented\r\nContent-Length:"
                b" 0\r\nConnection: close\r\n\r\n"
            )
            return

        target_file = resolve_safe_path(web_root, path)

        if target_file is None:
            body = b"<h1>404 Not Found</h1><p>Requested file is unavailable.</p>"
            header = (
                f"HTTP/1.1 404 Not Found\r\nServer: MiniApache-OS/1.0\r\nX-Served-By:"
                f" {worker_id}\r\nContent-Type: text/html\r\nContent-Length:"
                f" {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            client_sock.sendall(header + body)
            return

        _, ext = os.path.splitext(target_file)
        content_type = MIME_TYPES.get(ext.lower(), "application/octet-stream")
        file_size = os.path.getsize(target_file)

        range_header = headers.get("range")

        # =========================================================================
        # HTTP 206 Partial Content (Byte-Range Streaming for Videos & Audio)
        # Prevents thread starvation by sending small slices instead of full files
        # =========================================================================
        if range_header and range_header.startswith("bytes="):
            byte_range = range_header[6:].split("-")
            start = int(byte_range[0]) if byte_range[0] else 0
            end = int(byte_range[1]) if byte_range[1] else file_size - 1

            if start >= file_size:
                client_sock.sendall(
                    f"HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */{file_size}\r\n\r\n".encode()
                )
                return

            end = min(end, file_size - 1)
            content_length = (end - start) + 1

            header = (
                f"HTTP/1.1 206 Partial Content\r\nServer:"
                f" MiniApache-OS/1.0\r\nX-Served-By: {worker_id}\r\nAccept-Ranges:"
                f" bytes\r\nContent-Range: bytes"
                f" {start}-{end}/{file_size}\r\nContent-Type:"
                f" {content_type}\r\nContent-Length:"
                f" {content_length}\r\nConnection: close\r\n\r\n"
            ).encode()
            client_sock.sendall(header)

            # Seek directly to the requested byte position and stream only that slice
            with open(target_file, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    client_sock.sendall(chunk)
                    remaining -= len(chunk)
            return

        # Standard HTTP 200 OK for regular files (HTML, CSS, JS, small images)
        header = (
            f"HTTP/1.1 200 OK\r\nServer: MiniApache-OS/1.0\r\nX-Served-By:"
            f" {worker_id}\r\nAccept-Ranges: bytes\r\nContent-Type:"
            f" {content_type}\r\nContent-Length: {file_size}\r\nConnection:"
            " close\r\n\r\n"
        ).encode()
        client_sock.sendall(header)

        with open(target_file, "rb") as f:
            while chunk := f.read(64 * 1024):
                client_sock.sendall(chunk)

    except (
        ConnectionResetError,
        BrokenPipeError,
        ConnectionAbortedError,
        OSError,
    ):
        pass
