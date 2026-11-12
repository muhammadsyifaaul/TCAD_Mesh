"""Test raw RESP protocol with the FIXED *6 count."""
import socket, time

def set_nx(host, port, key, ttl_sec):
    key_b = key.encode()
    ttl_b = str(ttl_sec).encode()
    # FIXED: *6 not *5 — SET key value NX EX ttl = 6 elements
    cmd = (
        b"*6\r\n"
        b"$3\r\nSET\r\n"
        b"$" + str(len(key_b)).encode() + b"\r\n" + key_b + b"\r\n"
        b"$0\r\n\r\n"
        b"$2\r\nNX\r\n"
        b"$2\r\nEX\r\n"
        b"$" + str(len(ttl_b)).encode() + b"\r\n" + ttl_b + b"\r\n"
    )
    s = socket.create_connection((host, port), timeout=2)
    s.send(cmd)
    resp = s.recv(100)
    s.close()
    return resp

host = "redis"
port = 6379

key1 = "nonce:test:fixed_" + str(int(time.time()))
r1 = set_nx(host, port, key1, 180)
print(f"Fresh key RESP: {repr(r1)}")

r2 = set_nx(host, port, key1, 180)
print(f"Dup key RESP:   {repr(r2)}")

for label, resp in [("Fresh", r1), ("Dup", r2)]:
    line = resp.decode("utf-8", errors="replace").strip()
    # Only take the first line (ReadString reads until \n)
    line = line.split('\r\n')[0].strip()
    print(f"  {label}: first_line={repr(line)}")
    if line == "+OK":
        print(f"  → stored (fresh nonce) ✅")
    elif line in ("$-1", "*0", "+(nil)", "_") or line.startswith("_"):
        print(f"  → already exists (NX rejected) ✅")
    else:
        print(f"  → DEFAULT BRANCH → {repr(line)} — check response format")
