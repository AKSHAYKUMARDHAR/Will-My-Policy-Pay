"""The 17 terms on a fine-print card: names, canonical values and the fixed plain-English explanations.

The model only extracts structured values with quotes. Every sentence the user reads about a term
is written here, once, so it can be reviewed and never invents a number.
"""
from dataclasses import dataclass

# Canonical value strings follow data/LABEL_GUIDE.md, so the eval compares like with like.


@dataclass(frozen=True)
class Term:
    key: str
    name: str
    group: str          # what kind of value: limit | number | list | copay_senior | ncb | maternity
    kinds: tuple        # the model's allowed "kind" values
    hint: str           # extraction guidance for the prompt
    unit: str = ""


LIMIT_KINDS = ("no_limit", "up_to_si", "single_private_room", "shared_room", "percent_si", "amount", "varies",
               "not_covered", "options")

TERMS: list[Term] = [
    Term("room_rent", "Room rent limit", "limit", ("no_limit", "single_private_room", "shared_room", "percent_si", "amount", "options"),
         "The daily limit on the hospital room (room rent, boarding, nursing). For the insured's sum insured."),
    Term("icu", "ICU limit", "limit", ("no_limit", "percent_si", "amount", "options"),
         "The daily limit on intensive care (ICU/ICCU) charges."),
    Term("copay", "Co-payment", "number", ("percent",),
         "A share of every claim the insured pays, regardless of age. 0 if co-payment exists only as an optional cover the buyer can choose.",
         "%"),
    Term("copay_senior", "Co-payment for older members", "copay_senior", ("percent_age",),
         "A co-payment that applies because of age at entry. 'age' is the youngest entry age it applies to: '61 years and above' is 61, 'above 60' is 61."),
    Term("deductible", "Deductible", "number", ("amount",),
         "An amount the insured pays before the policy pays, in the base plan. 0 if a deductible exists only as an optional cover.", "₹"),
    Term("initial_waiting_days", "First waiting period", "number", ("days", "options"),
         "Days after the policy starts during which illnesses (not accidents) are not covered.", "days"),
    Term("ped_waiting_months", "Waiting period for pre-existing diseases", "number", ("months",),
         "Months before conditions the insured already had are covered.", "months"),
    Term("specific_waiting_months", "Waiting period for listed illnesses", "list", ("months",),
         "Months before the named illnesses and surgeries (cataract, hernia, joint replacement...) are covered. List every period the clause gives, in months (90 days = 3).",
         "months"),
    Term("maternity", "Maternity", "maternity", ("not_covered", "covered"),
         "Whether childbirth expenses are covered in the base plan (not an optional cover), and the waiting period in months if covered."),
    Term("pre_hosp_days", "Before admission", "number", ("days", "options"),
         "Days of medical expenses before admission that are covered.", "days"),
    Term("post_hosp_days", "After discharge", "number", ("days", "options"),
         "Days of medical expenses after discharge that are covered.", "days"),
    Term("cataract", "Cataract limit", "limit", ("amount", "percent_si", "options"),
         "A cap on cataract surgery in the base plan, per eye where stated. Not the waiting period."),
    Term("restoration", "Refill of cover", "number", ("percent",),
         "Restoration, reinstatement, recharge or reset of the sum insured once it is used up: the percentage of the sum insured restored.", "%"),
    Term("ncb", "Bonus for staying insured", "ncb", ("percent_max",),
         "Cumulative, no-claim or loyalty bonus: the yearly increase in sum insured (percent) and its maximum (max, percent)."),
    Term("ambulance", "Road ambulance", "limit", ("up_to_si", "amount", "percent_si", "options"),
         "The limit on road ambulance charges per hospitalisation."),
    Term("modern_treatments", "Modern treatments", "limit", ("up_to_si", "percent_si", "amount", "varies"),
         "The limit on IRDAI's listed modern treatments (robotic surgery, oral chemotherapy, stem cell therapy...). 'varies' if each treatment has its own cap."),
    Term("ayush", "AYUSH treatment", "limit", ("not_covered", "up_to_si", "percent_si", "amount"),
         "The limit on in-patient Ayurveda, Yoga, Unani, Siddha and Homeopathy treatment."),
]
BY_KEY = {t.key: t for t in TERMS}
KEYS = [t.key for t in TERMS]
WATCH = {"room_rent", "icu", "copay", "copay_senior", "deductible", "cataract", "ped_waiting_months"}


# ---- canonical values ------------------------------------------------------------------------------

def _num(x) -> str:
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:g}"


def _limit(kind: str, item: dict, term: str) -> str | None:
    if kind in ("no_limit", "up_to_si"):
        return "up_to_si" if term in ("ambulance", "modern_treatments", "ayush") else "no_limit"
    if kind in ("single_private_room", "shared_room", "varies", "not_covered"):
        return kind
    if kind == "percent_si" and item.get("percent") is not None:
        s = f"percent_si:{_num(item['percent'])}"
        return s + (f",cap:{_num(item['cap'])}" if item.get("cap") else "")
    if kind == "amount" and item.get("amount") is not None:
        return f"amount:{_num(item['amount'])}"
    return None


_OPTION = __import__("re").compile(r"^(no_limit|up_to_si|single_private_room|shared_room|percent_si:\d+(?:\.\d+)?(?:,cap:\d+)?|amount:\d+)$")


def _option(o, term: str) -> str | None:
    """One option of a menu: a code string ("percent_si:1,cap:5000") or a {kind, percent, cap, amount} object."""
    if isinstance(o, dict):
        return _limit(o.get("kind"), o, term)
    code = str(o).strip().lower().replace(" ", "").replace("₹", "")
    if not _OPTION.match(code):
        return None
    if code.startswith("percent_si:"):
        p, _, cap = code[11:].partition(",cap:")
        return _limit("percent_si", {"percent": float(p), "cap": float(cap) if cap else None}, term)
    if code.startswith("amount:"):
        return _limit("amount", {"amount": float(code[7:])}, term)
    return _limit(code, {}, term)


def canonical(term: str, obj: dict) -> str | None:
    """The model's structured answer for one term as a canonical string; None if it is malformed.
    A term the document doesn't state is 'not_stated'."""
    if not obj or not obj.get("found"):
        return "not_stated"
    t, kind = BY_KEY[term], obj.get("kind")
    if obj.get("value") is not None:          # the model sometimes puts the number in "value"
        obj = dict(obj)
        if kind == "amount" and obj.get("amount") is None:
            obj["amount"] = obj["value"]
        if kind == "percent_si" and obj.get("percent") is None:
            obj["percent"] = obj["value"]
    if t.group == "limit":
        if kind == "options":
            items = [_option(o, term) for o in obj.get("options") or []]
            items = sorted({i for i in items if i})
            return "options:" + "|".join(items) if len(items) > 1 else (items[0] if items else None)
        return _limit(kind, obj, term)
    if t.group == "number":
        if kind == "options" and obj.get("values"):
            vals = sorted({float(v) for v in obj["values"]})
            return "options:" + "|".join(_num(v) for v in vals) if len(vals) > 1 else _num(vals[0])
        v = obj.get("value", obj.get("percent", obj.get("amount")))
        return _num(v) if v is not None else None
    if t.group == "list":
        vals = obj.get("values") or ([obj["value"]] if obj.get("value") is not None else [])
        return ",".join(_num(v) for v in sorted({float(v) for v in vals})) if vals else None
    if t.group == "copay_senior":
        if obj.get("percent") is None or obj.get("age") is None:
            return None
        return f"{_num(obj['percent'])},age:{_num(obj['age'])}"
    if t.group == "ncb":
        if obj.get("percent") is None or obj.get("max") is None:
            return None
        return f"{_num(obj['percent'])},max:{_num(obj['max'])}"
    if t.group == "maternity":
        if kind == "not_covered":
            return "not_covered"
        if kind == "covered":
            return f"covered,waiting:{_num(obj['value'])}" if obj.get("value") else "covered"
    return None


def same(a: str | None, b: str | None) -> bool:
    """Canonical values are equal; option sets and lists of months compare as sets."""
    if a is None or b is None:
        return False
    if a.startswith("options:") and b.startswith("options:"):
        return set(a[8:].split("|")) == set(b[8:].split("|"))
    if "," in a and "," in b and ":" not in a + b:
        return set(a.split(",")) == set(b.split(","))
    return a == b


def value_numbers(canon: str) -> list[float]:
    """The numbers a canonical value relies on, which its quote must contain."""
    import re
    if canon.startswith("options:"):
        return []           # a menu is quoted in part; checked by the per-option logic in extract.py
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", canon)]
    return [n for n in nums if n != 0]


# ---- plain-English display -----------------------------------------------------------------------

def inr(x: float) -> str:
    """Indian digit grouping: 500000 -> '₹5,00,000'."""
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def lakh(x: float) -> str:
    if x >= 10000000:
        return f"₹{_num(x / 10000000)} crore"
    if x >= 100000:
        return f"₹{_num(round(x / 100000, 2))} lakh"
    return inr(x)


def _limit_text(item: str, si: float, per: str) -> str:
    if item in ("no_limit", "up_to_si"):
        return "No limit" if item == "no_limit" else "Covered up to your sum insured"
    if item == "single_private_room":
        return "A single private room"
    if item == "shared_room":
        return "A shared room"
    if item == "varies":
        return "A different cap for each treatment"
    if item == "not_covered":
        return "Not covered"
    if item.startswith("percent_si:"):
        parts = dict(p.split(":") for p in item.split(","))
        amount = float(parts["percent_si"]) / 100 * si
        if "cap" in parts:
            amount = min(amount, float(parts["cap"]))
            return f"Up to {inr(amount)}{per} ({parts['percent_si']}% of your cover, at most {inr(float(parts['cap']))})"
        return f"Up to {inr(amount)}{per} ({parts['percent_si']}% of your cover)"
    if item.startswith("amount:"):
        return f"Up to {inr(float(item.split(':')[1]))}{per}"
    return item


def describe(term: str, canon: str, si: float, age: int | None = None) -> dict:
    """{'value': short text, 'meaning': one sentence, 'watch': bool} for a shown term."""
    t = BY_KEY[term]
    per = {"room_rent": " a day", "icu": " a day", "cataract": " per eye", "ambulance": " per hospitalisation"}.get(term, "")
    if canon.startswith("options:") and t.group == "limit":
        opts = [_limit_text(o, si, per) for o in canon[8:].split("|")]
        return {"value": "Depends on your plan: " + "; ".join(opts),
                "meaning": "The policy offers these choices; your policy schedule says which one you bought.", "watch": True}
    if canon.startswith("options:"):
        opts = canon[8:].split("|")
        return {"value": f"Depends on your plan: {', '.join(opts[:-1])} or {opts[-1]} {t.unit}",
                "meaning": "The policy offers these choices; your policy schedule says which one you bought.", "watch": False}

    if term == "room_rent":
        if canon == "no_limit":
            return {"value": "No limit", "meaning": "Any room category is paid, up to your sum insured.", "watch": False}
        return {"value": _limit_text(canon, si, per),
                "meaning": "Pick a costlier room and the extra rent is yours to pay, and most doctor and surgery charges "
                           "are cut in the same proportion. Medicines, implants, tests and ICU charges are never cut this way.",
                "watch": True}
    if term == "icu":
        if canon == "no_limit":
            return {"value": "No limit", "meaning": "ICU charges are paid up to your sum insured.", "watch": False}
        return {"value": _limit_text(canon, si, per), "meaning": "ICU charges above this are yours to pay.", "watch": True}
    if term == "copay":
        p = float(canon)
        if p == 0:
            return {"value": "None in the base plan", "meaning": "You pay no fixed share of a claim, unless you chose a co-payment for a lower premium.", "watch": False}
        return {"value": f"You pay {_num(p)}% of every claim", "meaning": f"On a {inr(400000)} claim, that is {inr(4000 * p)} from your pocket.", "watch": True}
    if term == "copay_senior":
        p, a = canon.split(",age:")
        applies = age is not None and age >= float(a)
        return {"value": f"{p}% of every claim for members who joined at {a} or older",
                "meaning": ("This applies to you." if applies else "It applies to older family members, such as parents."),
                "watch": True}
    if term == "deductible":
        d = float(canon)
        if d == 0:
            return {"value": "None in the base plan", "meaning": "The policy pays from the first rupee of an admissible claim.", "watch": False}
        return {"value": f"You pay the first {inr(d)}", "meaning": "The policy pays only after this amount.", "watch": True}
    if term == "initial_waiting_days":
        return {"value": f"{canon} days", "meaning": "Illnesses in the first days after you buy are not covered. Accidents are covered from day one.", "watch": False}
    if term == "ped_waiting_months":
        m = float(canon)
        note = " That is longer than the 36 months IRDAI has allowed for new policies since 2024." if m > 36 else ""
        return {"value": f"{canon} months ({_num(m / 12)} years)",
                "meaning": "Conditions you had before buying (diabetes, blood pressure, and so on) are covered only after this, if you declared them." + note,
                "watch": m >= 36}
    if term == "specific_waiting_months":
        vals = canon.split(",")
        text = " / ".join(f"{v} months" for v in vals)
        return {"value": text, "meaning": "Named illnesses and surgeries (often cataract, hernia, joint replacement) are covered only after this.", "watch": False}
    if term == "maternity":
        if canon == "not_covered":
            return {"value": "Not covered in the base plan", "meaning": "Childbirth costs are not paid unless you add a maternity cover.", "watch": False}
        w = canon.split("waiting:")[1] if "waiting:" in canon else None
        return {"value": "Covered" + (f" after {w} months" if w else ""), "meaning": "Childbirth costs are paid within the policy's limits.", "watch": False}
    if term in ("pre_hosp_days", "post_hosp_days"):
        when = "before admission" if term == "pre_hosp_days" else "after discharge"
        return {"value": f"{canon} days {when}", "meaning": f"Tests, medicines and consultations for the same illness {when} are covered for this long.", "watch": False}
    if term == "cataract":
        return {"value": _limit_text(canon, si, per), "meaning": "Cataract surgery is paid only up to this, however much the hospital charges.", "watch": True}
    if term == "restoration":
        return {"value": f"{canon}% of your cover", "meaning": "Once your cover is used up in a year, it is refilled, usually only for a different illness.", "watch": False}
    if term == "ncb":
        p, m = canon.split(",max:")
        return {"value": f"+{p}% a year, up to {m}%", "meaning": "Your cover grows each year you renew. The policy's wording says whether a claim reduces it.", "watch": False}
    if term == "ambulance":
        low = canon.startswith("amount:") and float(canon.split(":")[1]) < 2000
        return {"value": _limit_text(canon, si, per), "meaning": "Road ambulance charges above this are yours to pay." if canon != "up_to_si" else "Road ambulance charges are covered.", "watch": low}
    if term == "modern_treatments":
        return {"value": _limit_text(canon, si, ""), "meaning": "Treatments such as robotic surgery, oral chemotherapy and stem cell therapy.", "watch": canon != "up_to_si"}
    if term == "ayush":
        return {"value": _limit_text(canon, si, ""), "meaning": "In-patient Ayurveda, Yoga, Unani, Siddha and Homeopathy treatment.", "watch": canon == "not_covered"}
    return {"value": canon, "meaning": "", "watch": False}
