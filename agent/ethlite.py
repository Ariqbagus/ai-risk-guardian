"""Minimal Ethereum toolkit in pure Python stdlib (no third-party packages).

Implements exactly what the AI agent needs:
  * Keccak-256 (Ethereum variant, suffix 0x01 -- NOT NIST SHA3-256)
  * secp256k1 key derivation and ECDSA signing (RFC 6979 deterministic nonces)
  * RLP encoding and legacy (EIP-155) transaction signing
  * A tiny JSON-RPC client over urllib

Self-test vectors (run `python3 ethlite.py`):
  keccak256(b"") == c5d24601...85a470
  privkey 0x00..01 -> address 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf
"""

import hashlib
import hmac as hmac_mod
import json
import struct
import urllib.request

# ---------------------------------------------------------------- Keccak-256

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_R = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK64 = (1 << 64) - 1


def _rotl64(x, n):
    return ((x << n) | (x >> (64 - n))) & _MASK64 if n else x


def _keccak_f1600(state):
    for rc in _RC:
        # theta
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x + 4) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(state[x + 5 * y], _R[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y])
        # iota
        state[0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136  # 1088-bit rate for 256-bit output
    state = [0] * 25
    # pad10*1 with Keccak suffix 0x01
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0x00)
    padded.append(0x80)
    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(rate // 8):
            state[i] ^= struct.unpack_from("<Q", block, i * 8)[0]
        _keccak_f1600(state)
    out = bytearray()
    for i in range(4):
        out += struct.pack("<Q", state[i])
    return bytes(out[:32])


def selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


# ---------------------------------------------------------------- secp256k1

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def _ec_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0]) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    y = (lam * (p[0] - x) - p[1]) % _P
    return (x, y)


def _ec_mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def privkey_to_address(privkey: bytes) -> str:
    x, y = _ec_mul(int.from_bytes(privkey, "big"), _G)
    pub = x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return "0x" + keccak256(pub)[-20:].hex()


def _rfc6979_nonce(privkey_int: int, msg_hash: bytes) -> int:
    bx = privkey_int.to_bytes(32, "big")
    bh = (int.from_bytes(msg_hash, "big") % _N).to_bytes(32, "big")
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac_mod.new(k, v + b"\x00" + bx + bh, hashlib.sha256).digest()
    v = hmac_mod.new(k, v, hashlib.sha256).digest()
    k = hmac_mod.new(k, v + b"\x01" + bx + bh, hashlib.sha256).digest()
    v = hmac_mod.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac_mod.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _N:
            return candidate
        k = hmac_mod.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac_mod.new(k, v, hashlib.sha256).digest()


def ecdsa_sign(privkey: bytes, msg_hash: bytes):
    """Returns (v_offset, r, s) with v_offset in {0, 1} (recovery id)."""
    d = int.from_bytes(privkey, "big")
    z = int.from_bytes(msg_hash, "big")
    k = _rfc6979_nonce(d, msg_hash)
    x, y = _ec_mul(k, _G)
    r = x % _N
    s = (pow(k, -1, _N) * (z + r * d)) % _N
    recid = (y & 1) | (2 if x >= _N else 0)
    if s > _N // 2:  # low-s rule (EIP-2)
        s = _N - s
        recid ^= 1
    return recid, r, s


# ---------------------------------------------------------------- RLP + tx

def rlp_encode(item) -> bytes:
    if isinstance(item, int):
        if item == 0:
            return rlp_encode(b"")
        return rlp_encode(item.to_bytes((item.bit_length() + 7) // 8, "big"))
    if isinstance(item, (bytes, bytearray)):
        item = bytes(item)
        if len(item) == 1 and item[0] < 0x80:
            return item
        return _rlp_prefix(0x80, item)
    if isinstance(item, (list, tuple)):
        payload = b"".join(rlp_encode(x) for x in item)
        return _rlp_prefix(0xC0, payload)
    raise TypeError(f"cannot RLP-encode {type(item)}")


def _rlp_prefix(offset, payload):
    if len(payload) <= 55:
        return bytes([offset + len(payload)]) + payload
    len_bytes = len(payload).to_bytes((len(payload).bit_length() + 7) // 8, "big")
    return bytes([offset + 55 + len(len_bytes)]) + len_bytes + payload


def sign_legacy_tx(privkey: bytes, *, nonce, gas_price, gas_limit, to, value, data, chain_id) -> bytes:
    """Signs an EIP-155 legacy transaction and returns the raw bytes."""
    to_bytes = bytes.fromhex(to[2:]) if to else b""
    unsigned = [nonce, gas_price, gas_limit, to_bytes, value, data, chain_id, 0, 0]
    tx_hash = keccak256(rlp_encode(unsigned))
    recid, r, s = ecdsa_sign(privkey, tx_hash)
    v = chain_id * 2 + 35 + recid
    signed = [nonce, gas_price, gas_limit, to_bytes, value, data, v, r, s]
    return rlp_encode(signed)


# ---------------------------------------------------------------- JSON-RPC

class Rpc:
    def __init__(self, url, timeout=30):
        self.url = url
        self.timeout = timeout
        self._id = 0

    def call(self, method, params):
        import http.client
        import time

        last_exc = None
        for attempt in range(6):
            self._id += 1
            body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
            req = urllib.request.Request(
                self.url, data=body, headers={"Content-Type": "application/json", "User-Agent": "risk-guardian-agent/1.0"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out = json.loads(resp.read())
            except (http.client.HTTPException, ConnectionError, TimeoutError, urllib.error.URLError) as exc:
                last_exc = exc
                time.sleep(min(2**attempt, 16))
                continue
            if "error" in out:
                raise RuntimeError(f"RPC {method} failed: {out['error']}")
            return out["result"]
        raise RuntimeError(f"RPC {method} failed after retries: {last_exc}")

    def get_transaction_count(self, address, block="pending"):
        return int(self.call("eth_getTransactionCount", [address, block]), 16)

    def gas_price(self):
        return int(self.call("eth_gasPrice", []), 16)

    def send_raw(self, raw: bytes):
        return self.call("eth_sendRawTransaction", ["0x" + raw.hex()])

    def wait_receipt(self, tx_hash, timeout_s=180, poll_s=2.0):
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            receipt = self.call("eth_getTransactionReceipt", [tx_hash])
            if receipt is not None:
                return receipt
            time.sleep(poll_s)
        raise TimeoutError(f"no receipt for {tx_hash} within {timeout_s}s")

    def eth_call(self, to, data_hex, block="latest"):
        return self.call("eth_call", [{"to": to, "data": data_hex}, block])


# ---------------------------------------------------------------- ABI helpers

def abi_uint(value: int) -> bytes:
    return (value % (1 << 256)).to_bytes(32, "big")


def abi_bool(value: bool) -> bytes:
    return abi_uint(1 if value else 0)


def abi_address(address: str) -> bytes:
    return b"\x00" * 12 + bytes.fromhex(address[2:])


def encode_call(signature: str, *args: bytes) -> str:
    return "0x" + (selector(signature) + b"".join(args)).hex()


if __name__ == "__main__":
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "keccak empty"
    assert (
        keccak256(b"Sync(uint112,uint112)").hex()
        == "1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
    ), "keccak Sync"
    assert privkey_to_address((1).to_bytes(32, "big")) == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf", "address vector"
    print("ethlite self-test: OK")
