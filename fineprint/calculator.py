"""What a hospital bill would pay: a deterministic calculator, never the model.

Order of deductions (each step is a line on the result):
1. Room: paid up to the policy's daily room limit.
2. Proportionate deduction: when the room costs more than the limit, room-linked charges (doctor,
   surgeon, anaesthetist and OT fees) are paid in the same ratio as the room rent. IRDAI exempts
   medicines and consumables, implants and devices, diagnostics and ICU charges, and bars the cut in
   hospitals that don't charge by room category (IRDAI/HLT/REG/CIR/151/06/2020).
3. ICU: paid up to the daily ICU limit; never cut in proportion.
4. Non-medical items (IRDAI's List I: gloves, attendant food, toiletries...) are not paid.
5. A procedure sub-limit (cataract) caps the claim.
6. Deductible, then co-payment, then the sum insured.

Simplifications, stated on the page: room-linked charges are one figure for the whole stay, and an
age-based co-payment, when it applies, replaces a general one rather than adding to it.
"""
from dataclasses import dataclass, field

from .terms import inr

IRDAI_PD = "IRDAI/HLT/REG/CIR/151/06/2020"


@dataclass
class Bill:
    days: int = 0                   # days in a ward or room
    room_rate: float = 0            # charged per day
    icu_days: int = 0
    icu_rate: float = 0
    doctor_ot: float = 0            # surgeon, anaesthetist, consultant and OT charges (room-linked)
    medicines: float = 0            # pharmacy and consumables
    diagnostics: float = 0
    implants: float = 0             # implants, stents, lenses, devices
    non_medical: float = 0          # items IRDAI lists as not payable
    pre_post: float = 0             # pre- and post-hospitalisation expenses
    procedure: str = "other"        # "cataract" applies the cataract limit
    eyes: int = 1
    differential_billing: bool = True        # does the hospital charge doctor/OT fees by room category?
    category_rate: float | None = None       # for a room-category limit: what that category costs at this hospital


@dataclass
class Terms:
    sum_insured: float
    room: str | None = None         # canonical values from terms.py; None = not found in the document
    icu: str | None = None
    copay: float | None = 0         # None = not confirmed: treated as none, with a caveat
    copay_senior: str | None = None
    age: int = 40
    deductible: float | None = 0
    cataract: str | None = None


@dataclass
class Line:
    item: str
    billed: float
    pays: float
    reason: str = ""

    @property
    def you(self) -> float:
        return self.billed - self.pays


@dataclass
class Result:
    lines: list
    adjustments: list               # [(label, amount the insurer stops paying, reason)]
    billed: float
    insurer: float
    you: float
    caveats: list = field(default_factory=list)
    saving_if_within_limit: float | None = None
    room_limit_rate: float | None = None


def _daily_cap(term: str | None, si: float) -> float | None:
    """Rupees a day for a limit, or None when there is no rupee cap (no limit, room category, unknown)."""
    if not term or term in ("no_limit", "up_to_si", "single_private_room", "shared_room") or term.startswith("options:"):
        return None
    if term.startswith("percent_si:"):
        parts = dict(p.split(":") for p in term.split(","))
        cap = float(parts["percent_si"]) / 100 * si
        return min(cap, float(parts["cap"])) if "cap" in parts else cap
    if term.startswith("amount:"):
        return float(term.split(":")[1])
    return None


def _cataract_cap(term: str | None, si: float) -> float | None:
    if not term or term.startswith("options:"):
        return None
    if term.startswith("amount:"):
        return float(term.split(":")[1])
    if term.startswith("percent_si:"):
        parts = dict(p.split(":") for p in term.split(","))
        cap = float(parts["percent_si"]) / 100 * si
        return min(cap, float(parts["cap"])) if "cap" in parts else cap
    return None


def _copay_percent(t: Terms) -> tuple[float, str]:
    if t.copay_senior:
        p, age = t.copay_senior.split(",age:")
        if t.age >= float(age):
            return float(p), f"{p}% co-payment for members who joined at {age} or older"
    if t.copay:
        return float(t.copay), f"{t.copay:g}% co-payment on every claim"
    return 0.0, ""


def simulate(bill: Bill, t: Terms, _compare: bool = True) -> Result:
    si = t.sum_insured
    lines, caveats = [], []

    # 1-2. room and the proportionate deduction
    room_billed = bill.days * bill.room_rate
    cap = _daily_cap(t.room, si)
    ratio, room_reason, limit_rate = 1.0, "", None
    if t.room in ("single_private_room", "shared_room"):
        name = "a single private room" if t.room == "single_private_room" else "a shared room"
        if bill.category_rate and bill.room_rate > bill.category_rate:
            limit_rate = bill.category_rate
            room_reason = f"Your policy pays for {name}; at this hospital that costs {inr(limit_rate)} a day"
    elif cap is not None and bill.room_rate > cap:
        limit_rate = cap
        room_reason = f"Your room limit is {inr(cap)} a day"
    elif t.room is None and room_billed:
        caveats.append("The room-rent limit wasn't found in the document, so this assumes there is none. Check your policy schedule.")
    if limit_rate is not None and bill.room_rate > 0:
        ratio = limit_rate / bill.room_rate
    room_pays = bill.days * min(bill.room_rate, limit_rate) if limit_rate is not None else room_billed
    if room_billed:
        lines.append(Line(f"Room, {bill.days} days at {inr(bill.room_rate)}", room_billed, room_pays, room_reason))

    # 3. ICU
    icu_billed = bill.icu_days * bill.icu_rate
    icu_cap = _daily_cap(t.icu, si)
    if icu_billed:
        if icu_cap is not None and bill.icu_rate > icu_cap:
            lines.append(Line(f"ICU, {bill.icu_days} days at {inr(bill.icu_rate)}", icu_billed, bill.icu_days * icu_cap,
                              f"Your ICU limit is {inr(icu_cap)} a day. ICU charges are never cut in proportion ({IRDAI_PD})"))
        else:
            if t.icu is None:
                caveats.append("The ICU limit wasn't found in the document, so this assumes there is none.")
            lines.append(Line(f"ICU, {bill.icu_days} days at {inr(bill.icu_rate)}", icu_billed, icu_billed))

    # 2. room-linked charges
    if bill.doctor_ot:
        if ratio < 1 and bill.differential_billing:
            lines.append(Line("Doctor, surgeon and OT charges (room-linked)", bill.doctor_ot, bill.doctor_ot * ratio,
                              f"Proportionate deduction: paid at {ratio:.1%}, the same share as your room rent"))
        elif ratio < 1:
            lines.append(Line("Doctor, surgeon and OT charges (room-linked)", bill.doctor_ot, bill.doctor_ot,
                              f"Not cut: the hospital doesn't charge by room category ({IRDAI_PD})"))
        else:
            lines.append(Line("Doctor, surgeon and OT charges", bill.doctor_ot, bill.doctor_ot))
    exempt = "Never cut in proportion to the room rent (" + IRDAI_PD + ")" if ratio < 1 else ""
    for label, amount in (("Medicines and consumables", bill.medicines), ("Diagnostics and tests", bill.diagnostics),
                          ("Implants and devices", bill.implants)):
        if amount:
            lines.append(Line(label, amount, amount, exempt))
    if bill.pre_post:
        lines.append(Line("Before admission and after discharge", bill.pre_post, bill.pre_post))
    # 4. non-medical items
    if bill.non_medical:
        lines.append(Line("Non-medical items (gloves, attendant food, toiletries...)", bill.non_medical, 0.0,
                          "Not payable under IRDAI's list of non-medical items, unless you have a consumables cover"))

    billed = sum(l.billed for l in lines)
    admissible = sum(l.pays for l in lines)
    adjustments = []

    # 5. procedure sub-limit
    if bill.procedure == "cataract":
        per_eye = _cataract_cap(t.cataract, si)
        if per_eye is not None:
            limit = per_eye * max(1, bill.eyes)
            if admissible > limit:
                adjustments.append(("Cataract limit", admissible - limit, f"Cataract is paid up to {inr(per_eye)} per eye"))
                admissible = limit
        elif t.cataract is None:
            caveats.append("No cataract limit was found in the document; check your schedule for one.")
    # 6. deductible, co-payment, sum insured
    if t.deductible is None:
        caveats.append("No deductible was confirmed from the document, so this assumes there is none. Check your policy schedule.")
    if t.copay is None:
        caveats.append("No co-payment was confirmed from the document, so this assumes there is none. Check your policy schedule.")
    if t.deductible:
        d = min(t.deductible, admissible)
        adjustments.append(("Deductible", d, f"You pay the first {inr(t.deductible)}"))
        admissible -= d
    pct, why = _copay_percent(t)
    if pct:
        c = admissible * pct / 100
        adjustments.append(("Co-payment", c, why))
        admissible -= c
    if admissible > si:
        adjustments.append(("Sum insured", admissible - si, f"The policy pays at most your sum insured of {inr(si)}"))
        admissible = si

    insurer = round(admissible)
    result = Result([Line(l.item, round(l.billed), round(l.pays), l.reason) for l in lines],
                    [(a, round(b), c) for a, b, c in adjustments],
                    round(billed), insurer, round(billed) - insurer, caveats, room_limit_rate=limit_rate)

    # what choosing a room within the limit would save
    if _compare and limit_rate is not None and bill.room_rate > limit_rate:
        within = Bill(**{**bill.__dict__, "room_rate": limit_rate})
        other = simulate(within, t, _compare=False)
        result.saving_if_within_limit = result.you - other.you
    return result
