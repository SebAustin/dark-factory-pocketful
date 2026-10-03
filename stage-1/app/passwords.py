"""Password hashing with stdlib scrypt. Stored form: scrypt$n$r$p$salt_hex$hash_hex."""
import hashlib
import hmac
import secrets
from concurrent.futures import ThreadPoolExecutor

N, R, P = 2 ** 14, 8, 1
# Seeded fixture users: a lighter cost keeps a large reset inside its 10 s budget (plan D7).
SEED_N = 2 ** 11
MAXMEM = 64 * 1024 * 1024


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=MAXMEM, dklen=32)


def hash_password(password: str, n: int = N) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, n, R, P)
    return "scrypt${}${}${}${}${}".format(n, R, P, salt.hex(), digest.hex())


def hash_many(passwords_, n: int = SEED_N) -> dict:
    """Hash each distinct password once, in parallel (scrypt releases the GIL)."""
    distinct = list(dict.fromkeys(passwords_))
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(distinct, pool.map(lambda pw: hash_password(pw, n), distinct)))


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = _derive(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)
