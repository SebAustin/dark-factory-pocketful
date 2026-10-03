"""Password hashing with stdlib scrypt. Stored form: scrypt$n$r$p$salt_hex$hash_hex."""
import hashlib
import hmac
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

N, R, P = 2 ** 14, 8, 1
# Seeded fixture users: a lighter cost keeps a large reset inside its 10 s budget (plan D7).
SEED_N = 2 ** 11
MAXMEM = 64 * 1024 * 1024
# One interactive hash at a time. Parallel scrypt threads burn the container's 2 CPU quota in a
# few milliseconds, the cgroup then throttles every thread, and unrelated requests stall
# (decision D-19). Queueing 50 callers costs 50 x ~44 ms, well inside the 5 s request limit.
_HASH_SLOT = threading.BoundedSemaphore(1)


def _derive(password: str, salt: bytes, n: int, r: int, p: int, limited: bool = True) -> bytes:
    if not limited:
        return _scrypt(password, salt, n, r, p)
    with _HASH_SLOT:
        return _scrypt(password, salt, n, r, p)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=MAXMEM, dklen=32)


def hash_password(password: str, n: int = N, limited: bool = True) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, n, R, P, limited)
    return "scrypt${}${}${}${}${}".format(n, R, P, salt.hex(), digest.hex())


def hash_many(passwords_, n: int = SEED_N) -> dict:
    """Hash each distinct password once, in parallel (scrypt releases the GIL).

    Not limited by _HASH_SLOT: a 2000-user reset must finish inside its 10 s budget.
    """
    distinct = list(dict.fromkeys(passwords_))
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(distinct, pool.map(lambda pw: hash_password(pw, n, limited=False), distinct)))


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = _derive(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)
