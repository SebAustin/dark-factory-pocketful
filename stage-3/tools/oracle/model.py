"""Reference model of Pocketful stage 3 money history, written from the specification alone.

It knows nothing about the service's code. It is fed the facts the service itself reports (payment
`created_at`, correction `recorded_at`/`effective_at`, authorization, capture and void times) and
computes what every historical read must answer. Pure functions over plain data; no I/O.

Binding readings of open points (stage-3/docs/decisions): D-41 one monotonic microsecond clock, every server instant
unique; D-42 instant grammar (1-9 fraction digits, T/t, Z/z or +-HH:MM, no leap second, a space before a trailing
HH:MM offset in a QUERY value is a decoded '+'), exact comparison, last repeated parameter wins; D-43 one read instant N
per read (T = as_of or N, K = known_at or N); D-44 seeded ties by id, code-point order; D-45 openings; D-46 correction
error order 404 -> 403 -> linked -> stale -> insufficient_funds -> historical_overdraft; D-48 selection algorithm;
D-49 statement shape, from > to is 422, from = to is empty; D-50 snapshots; D-51 hold intervals; D-53 overdraft check.

Spec points encoded (runlog/stage3-spec.md, with stage 2 for holds):
  S3-TS    payment created_at is its original recorded and effective time (revision 1).
  S3-OPEN  opening balance = seeded ending balance - net effect of the ORIGINAL seeded payments;
           corrections never change it; new accounts open at 0.
  S3-SEL   known_at: each payment contributes its latest revision recorded at or before known_at;
           none recorded yet -> contributes nothing. Omitted known_at = everything known now.
  S3-EFF   a selected revision moves money (replaces the earlier amount) at ITS effective_at.
  S3-ASOF  as_of is inclusive: effective_at <= as_of counts; before everything -> opening balance.
  S3-STMT  statement window is half-open [from, to), entries oldest first by (effective_at, payment id),
           opening = balance just before `from`, closing = balance just before `to`,
           opening + sum(delta) == closing, balance_after is cumulative from the full-window opening and
           does not depend on limit/offset; zero-amount revisions are entries with delta 0.
  S3-ONLY  a statement lists only the caller's own sent/received payments.
  S3-HOLD  hold starts at authorization creation; a nonfinal capture reduces it at capture time; a final
           capture, void or expiry releases the remainder at that event's time; expiry at expires_at is known
           as soon as creation is known; other events are known at their own time (<= known_at);
           balance == total; available == total - held, in the SAME (as_of, known_at) view.
  S3-CORR  a correction moves (new - old) between the same two wallets; the sender is debited on an increase,
           the receiver on a decrease; a currently unaffordable debit is insufficient_funds (precedence);
           otherwise negative total or available at any past boundary is historical_overdraft; a stale
           expected_revision is stale_revision; settlement members and captures are immutable.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
NEG = datetime.min.replace(tzinfo=UTC)
POS = datetime.max.replace(tzinfo=UTC)


RFC3339 = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?([Zz]|[+-]\d{2}:\d{2})$")


def parse(text):
    """D-42: RFC 3339 with an offset -> aware UTC datetime (microseconds; the clock never goes finer).

    Raises ValueError for naive times, bare dates, empty values, a space instead of T, a leap second (:60),
    offsets beyond +-23:59 and more than nine fraction digits."""
    m = RFC3339.match(text) if isinstance(text, str) else None
    if not m:
        raise ValueError(text)
    year, month, day, hh, mm, ss, frac, off = m.groups()
    if int(ss) > 59 or int(hh) > 23 or int(mm) > 59:
        raise ValueError(text)
    micro = int((frac or "0").ljust(9, "0")[:6])
    if off in ("Z", "z"):
        tz = UTC
    else:
        oh, om = int(off[1:3]), int(off[4:6])
        if oh > 23 or om > 59:
            raise ValueError(text)
        tz = timezone((1 if off[0] == "+" else -1) * timedelta(hours=oh, minutes=om))
    return datetime(int(year), int(month), int(day), int(hh), int(mm), int(ss), micro, tzinfo=tz).astimezone(UTC)


def parse_query(text):
    """D-42: a query value whose only defect is ONE space right before a trailing HH:MM offset is a decoded '+'."""
    if isinstance(text, str) and re.search(r" \d{2}:\d{2}$", text) and text.count(" ") == 1:
        text = re.sub(r" (\d{2}:\d{2})$", r"+\1", text)
    return parse(text)


def fmt(value):
    return value.astimezone(UTC).isoformat(timespec="seconds")


@dataclass
class Rev:
    n: int
    amount: int
    effective_at: datetime
    recorded_at: datetime
    reason: str = ""


@dataclass
class Pay:
    id: str
    frm: str
    to: str
    created_at: datetime
    kind: str = "plain"            # plain | settlement | capture
    visibility: str = "public"
    revs: list = field(default_factory=list)

    def current(self):
        return self.revs[-1]


@dataclass
class Auth:
    id: str
    frm: str
    to: str
    amount: int
    created_at: datetime
    expires_at: datetime
    captures: list = field(default_factory=list)   # payment ids, in order
    close: tuple = None                            # ("captured" | "voided", datetime) or None


class Model:
    def __init__(self, opening=None):
        self.opening = dict(opening or {})
        self.payments = {}
        self.auths = {}

    # ------------------------------------------------------------ building the log
    @classmethod
    def from_seed(cls, ending_balances, seeded_payments):
        """seeded_payments: [(id, frm, to, amount, created_at(datetime), visibility)] in the fixture."""
        net = {u: 0 for u in ending_balances}
        for _, frm, to, amount, _, _ in seeded_payments:
            net[frm] -= amount
            net[to] += amount
        model = cls({u: ending_balances[u] - net[u] for u in ending_balances})
        for pid, frm, to, amount, created, visibility in seeded_payments:
            model.add_payment(pid, frm, to, amount, created, visibility=visibility)
        return model

    def add_user(self, user):
        self.opening.setdefault(user, 0)

    def add_payment(self, pid, frm, to, amount, created_at, kind="plain", visibility="public"):
        pay = Pay(pid, frm, to, created_at, kind, visibility, [Rev(1, amount, created_at, created_at, "")])
        self.payments[pid] = pay
        return pay

    def add_revision(self, pid, n, amount, effective_at, recorded_at, reason=""):
        pay = self.payments[pid]
        assert n == len(pay.revs) + 1, f"revision {n} after {len(pay.revs)}"
        assert recorded_at > pay.revs[-1].recorded_at, "recorded times must strictly increase"
        pay.revs.append(Rev(n, amount, effective_at, recorded_at, reason))

    def add_auth(self, aid, frm, to, amount, created_at, expires_at):
        self.auths[aid] = Auth(aid, frm, to, amount, created_at, expires_at)

    def add_capture(self, aid, pid):
        self.auths[aid].captures.append(pid)

    def close_auth(self, aid, how, at):
        self.auths[aid].close = (how, at)

    # ------------------------------------------------------------ selection and balances
    def selected(self, known_at):
        """[(Pay, Rev)] for every payment with a revision recorded at or before known_at."""
        out = []
        for pay in self.payments.values():
            chosen = None
            for rev in pay.revs:
                if known_at is None or rev.recorded_at <= known_at:
                    chosen = rev
            if chosen is not None:
                out.append((pay, chosen))
        return out

    @staticmethod
    def delta(pay, rev, user):
        if user == pay.to:
            return rev.amount
        if user == pay.frm:
            return -rev.amount
        return 0

    def total(self, user, as_of, known_at, inclusive=True):
        """Balance of `user`: opening + selected revisions whose effective time is <= as_of (or < as_of)."""
        value = self.opening.get(user, 0)
        for pay, rev in self.selected(known_at):
            when = rev.effective_at
            if (when <= as_of) if inclusive else (when < as_of):
                value += self.delta(pay, rev, user)
        return value

    def held(self, user, as_of, known_at):
        total = 0
        for auth in self.auths.values():
            if auth.frm != user:
                continue
            if known_at is not None and auth.created_at > known_at:
                continue                       # creation not known yet
            if auth.created_at > as_of:
                continue                       # not created yet in this view
            if auth.expires_at <= as_of:
                continue                       # expiry is known once creation is known
            if auth.close is not None:
                _, at = auth.close
                if at <= as_of and (known_at is None or at <= known_at):
                    continue                   # final capture / void known and already happened
            reserved = auth.amount
            for pid in auth.captures:
                cap = self.payments[pid]
                if cap.created_at <= as_of and (known_at is None or cap.created_at <= known_at):
                    reserved -= cap.revs[0].amount
            total += max(reserved, 0)
        return total

    def me(self, user, as_of, known_at, now):
        """The four money fields of GET /me for a view. as_of None = current (holds: the read's start)."""
        total = self.total(user, POS if as_of is None else as_of, known_at)
        held = self.held(user, now if as_of is None else as_of, known_at)
        return {"balance": total, "total": total, "available": total - held, "held": held}

    # ------------------------------------------------------------ statements
    def statement(self, user, frm, to, known_at, now, id_key=None):
        """Full (unpaged) statement. frm/to None = opening of the wallet / now."""
        frm_v = NEG if frm is None else frm
        to_v = now if to is None else to
        key = id_key or (lambda pid: pid)
        mine = [(pay, rev) for pay, rev in self.selected(known_at) if user in (pay.frm, pay.to)]
        mine.sort(key=lambda pr: (pr[1].effective_at, key(pr[0].id)))
        opening = self.opening.get(user, 0) + sum(
            self.delta(p, r, user) for p, r in mine if r.effective_at < frm_v)
        entries, balance = [], opening
        for pay, rev in mine:
            if not (frm_v <= rev.effective_at < to_v):
                continue
            d = self.delta(pay, rev, user)
            balance += d
            entries.append({"id": pay.id, "revision": rev.n, "amount": rev.amount, "delta": d,
                            "balance_after": balance, "effective_at": rev.effective_at, "recorded_at": rev.recorded_at})
        closing = self.opening.get(user, 0) + sum(
            self.delta(p, r, user) for p, r in mine if r.effective_at < to_v)
        assert opening + sum(e["delta"] for e in entries) == closing, "model invariant: opening + deltas == closing"
        return {"opening_balance": opening, "entries": entries, "closing_balance": closing}

    # ------------------------------------------------------------ corrections
    def boundaries(self, upto):
        """Every effective/event instant <= upto under the latest known revisions."""
        times = set()
        for pay in self.payments.values():
            times.add(pay.current().effective_at)
        for auth in self.auths.values():
            times.add(auth.created_at)
            times.add(auth.expires_at)
            if auth.close:
                times.add(auth.close[1])
            for pid in auth.captures:
                times.add(self.payments[pid].created_at)
        return sorted(t for t in times if t <= upto)

    def correction_result(self, pid, actor, expected_revision, amount, effective_at, now):
        """D-46 order for a VALID body: 404 -> 403 -> linked_payment_immutable -> stale_revision ->
        insufficient_funds (current available of the debited party) -> historical_overdraft (D-53) -> ok."""
        pay = self.payments.get(pid)
        if pay is None:
            return "404"
        if actor != pay.frm:
            return "403"
        if pay.kind in ("settlement", "capture"):
            return "linked_payment_immutable"
        if expected_revision != len(pay.revs):
            return "stale_revision"
        diff = amount - pay.current().amount
        if diff != 0:
            payer = pay.frm if diff > 0 else pay.to
            if self.me(payer, None, None, now)["available"] < abs(diff):
                return "insufficient_funds"
        if self._would_overdraw(pay, amount, effective_at, now):
            return "historical_overdraft"
        return "ok"

    def correction_outcomes(self, *args):
        """Set form of correction_result, kept for callers that accept several answers."""
        return {self.correction_result(*args)}

    def _would_overdraw(self, pay, amount, effective_at, now):
        rec = max(now, pay.current().recorded_at + timedelta(microseconds=1))
        trial = Model(self.opening)
        trial.payments = {k: Pay(v.id, v.frm, v.to, v.created_at, v.kind, v.visibility, list(v.revs)) for k, v in self.payments.items()}
        trial.auths = self.auths
        trial.payments[pay.id].revs.append(Rev(len(pay.revs) + 1, amount, effective_at, rec, "trial"))
        users = {pay.frm, pay.to}
        for t in trial.boundaries(now) + [NEG]:
            for user in users:
                total = trial.total(user, t, None)
                if total < 0 or total - trial.held(user, t, None) < 0:
                    return True
        return False
