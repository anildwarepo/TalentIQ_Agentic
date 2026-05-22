"""Probe what the PG server does after we send the SSLRequest packet."""
import socket
import struct
import sys

HOST = "10.0.4.18"
PORT = 5432

s = socket.create_connection((HOST, PORT), timeout=10)
s.settimeout(10)  # also cap recv
print(f"TCP connected from {s.getsockname()} to {HOST}:{PORT}", flush=True)
s.sendall(struct.pack(">II", 8, 80877103))  # PG SSLRequest
try:
    b = s.recv(1)
    if b == b"S":
        print("OK: server says S (will negotiate TLS)")
    elif b == b"N":
        print("OK: server says N (will use plaintext)")
    elif b == b"":
        print("FAIL: server closed connection (firewall reject)")
    else:
        print(f"UNKNOWN response: {b!r}")
except socket.timeout:
    print("FAIL: recv timed out — no response from server")
finally:
    s.close()
