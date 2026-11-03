"""Public-network-only forward proxy. Each upstream connection uses a checked IP.

DNS is resolved once per TCP connection; the chosen IP, not the hostname, is
passed to open_connection. The browser never receives an unvalidated redirect
exception. This is an egress control, not an OS-level isolation guarantee.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from urllib.parse import urlsplit


def public_address(value: str) -> bool:
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def validate_url(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("只允许不含凭据的公网 HTTP/HTTPS 地址")
    if parsed.port not in (None, 80, 443):
        raise ValueError("只允许标准网页端口")
    host = parsed.hostname.encode("idna").decode("ascii")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("不能访问本机或内部网络")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not public_address(host):
            raise ValueError("不能访问非公网地址")
    return host, parsed.port or (443 if parsed.scheme == "https" else 80)


class PublicProxy:
    def __init__(self):
        self.server = None
        self.connections: set[asyncio.Task] = set()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=32768)
        return self.server.sockets[0].getsockname()[1]

    async def connect(self, host: str, port: int):
        if port not in (80, 443):
            raise ValueError("port denied")
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
        ips = list(dict.fromkeys(item[4][0] for item in addresses))
        if not ips or not all(public_address(ip) for ip in ips):
            raise ValueError("address denied")
        # Numeric IP pins the validated resolution, preventing DNS TOCTOU/rebinding.
        return await asyncio.open_connection(ips[0], port)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        upstream = None
        try:
            async with asyncio.timeout(20):
                header = await reader.readuntil(b"\r\n\r\n")
                lines = header.decode("iso-8859-1").split("\r\n")
                method, target, version = lines[0].split(" ", 2)
                if method == "CONNECT":
                    host, port = validate_url("https://" + target)
                    remote, upstream = await self.connect(host, port)
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    host, port = validate_url(target)
                    remote, upstream = await self.connect(host, port)
                    parsed = urlsplit(target)
                    path = parsed.path or "/"
                    if parsed.query:
                        path += "?" + parsed.query
                    kept = [
                        line
                        for line in lines[1:]
                        if line and not line.lower().startswith(("proxy-", "connection:", "host:"))
                    ]
                    forwarded = (
                        f"{method} {path} {version}\r\nHost: {parsed.netloc}\r\n"
                        + "\r\n".join(kept)
                        + "\r\nConnection: close\r\n\r\n"
                    )
                    upstream.write(forwarded.encode("iso-8859-1"))
                    await upstream.drain()

            async def copy(source, destination):
                while data := await asyncio.wait_for(source.read(65536), 90):
                    destination.write(data)
                    await destination.drain()

            tasks = [
                asyncio.create_task(copy(reader, upstream)),
                asyncio.create_task(copy(remote, writer)),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for item in tasks:
                    item.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (Exception, asyncio.CancelledError):
            with contextlib.suppress(Exception):
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        finally:
            for stream in (writer, upstream):
                if stream:
                    stream.close()
                    with contextlib.suppress(Exception):
                        await stream.wait_closed()
            self.connections.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        tasks = list(self.connections)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
