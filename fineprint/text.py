"""PDF text, quote matching and number checks.

Quotes are matched on letters and digits only (after Unicode NFKC): text extracted from PDFs often
drops or adds spaces ("specifiedinPolicySchedule"), splits words ("we re incurred") and uses
ligatures ("ﬁrst"), so a verbatim quote from the model rarely matches the raw text character for
character, but its letters and digits do.
"""
import io
import re
import unicodedata

from pypdf import PdfReader

MIN_QUOTE = 12          # letters and digits; shorter quotes ("Co-Payment 5%") prove too little


def compact(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", s or "").lower())


def pdf_pages(data: bytes) -> list[str]:
    """Text of each page, in order (page 1 = index 0). Empty strings for pages with no text layer."""
    reader = PdfReader(io.BytesIO(data))
    return [(p.extract_text() or "") for p in reader.pages]


def is_scanned(pages: list[str]) -> bool:
    """True when most pages have no text layer, so quotes can't be checked."""
    if not pages:
        return True
    empty = sum(1 for t in pages if len(compact(t)) < 40)
    return empty / len(pages) > 0.5


def fragments(quote: str) -> list[str]:
    """A quote may join passages with '...'; each passage is checked on its own."""
    parts = [compact(p) for p in re.split(r"\.\s*\.\s*\.|…", quote or "")]
    return [p for p in parts if len(p) >= 6]


def locate(quote: str, pages: list[str], cited: int | None) -> int | None:
    """Page number (1-based) where the quote appears: the cited page first, then its neighbours,
    then anywhere. Every '...'-joined passage must be in the document, the first one on the
    returned page. None if the quote is too short or not in the document."""
    parts = fragments(quote)
    if not parts or sum(len(p) for p in parts) < MIN_QUOTE:
        return None
    compacted = [compact(t) for t in pages]
    whole = "".join(compacted)
    if any(p not in whole for p in parts[1:]):
        return None
    order = []
    if cited and 1 <= cited <= len(pages):
        order += [cited, cited - 1, cited + 1]
    order += range(1, len(pages) + 1)
    for n in order:
        if 1 <= n <= len(pages) and parts[0] in compacted[n - 1]:
            return n
    return None


_WORDS = {
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "forty-five": 45, "sixty": 60,
    "ninety": 90, "one hundred twenty": 120, "one hundred and twenty": 120, "one hundred eighty": 180,
    "one hundred and eighty": 180, "twelve": 12, "eighteen": 18, "twenty four": 24, "twenty-four": 24,
    "thirty six": 36, "thirty-six": 36, "forty eight": 48, "forty-eight": 48, "five": 5, "ten": 10,
    "two": 2, "three": 3, "four": 4,
}


def numbers_in(text: str) -> set[float]:
    """Every number written in the text, as digits ("5,00,000" -> 500000) or common words ("thirty")."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    found = {float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}
    for word, value in _WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            found.add(float(value))
    if re.search(r"\blakh?s?\b|\blac\b", t):        # "Rs 2 Lakh" -> 200000
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*(?:lakh?s?|lac)\b", t):
            found.add(float(m) * 100000)
    if re.search(r"\bcrore\b", t):
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*crores?\b", t):
            found.add(float(m) * 10000000)
    # waiting periods written in days or years also count in months: "90 days" = 3, "two years" = 24
    for m in re.findall(r"(\d+)\s*days?\b", t):
        if int(m) % 30 == 0:
            found.add(float(int(m) // 30))
    for word, value in {**{str(i): i for i in range(1, 6)}, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.items():
        if re.search(rf"\b{word}\s*(?:\(\d\)\s*)?(?:year|yr)s?\b", t):
            found.add(float(value * 12))
    return found


# A categorical value must be backed by words that say it, not just by a quote about the benefit:
# "Expenses incurred towards Ambulance" lists a benefit; it doesn't say "up to the sum insured".
CATEGORY_WORDS = {
    "no_limit": ("suminsured", "nolimit", "actual", "uptosi", "nosublimit", "norestriction", "nocapping", "anyroom"),
    "up_to_si": ("suminsured", "nolimit", "actual", "uptosi", "nosublimit", "norestriction"),
    "single_private_room": ("single", "private"),
    "shared_room": ("shared", "twin", "generalward", "sharing"),
    "not_covered": ("excl", "notcovered", "notpayable", "willnotpay", "shallnot", "notbecovered"),
    "varies": ("table", "each", "against", "specified", "below"),
}


def words_support(quote: str, category: str) -> bool:
    words = CATEGORY_WORDS.get(category)
    if not words:
        return True
    q = compact(quote)
    return any(w in q for w in words)


# "None" or "up to the sum insured" must be said of the item for everyone. Two kinds of sentence only
# seem to say it (both found on the dev set):
# - an exemption for some people is not "no co-payment": "This co-payment will not apply for those insured
#   persons who have entered the policy before attaining 61 years of age"; "Insured paying premium as per
#   Zone I can avail treatment in Zone I, Zone II, Zone III and Zone IV without copayment"
# - a ceiling shared by several covers is not the item's own limit: "Our maximum liability collectively for
#   Hospitalization expenses, ... Ayurvedic / Homeopathic Hospitalisation Expenses ... would not exceed the
#   hospitalization Sum Insured" (the AYUSH clause itself sets a lower, plan-specific limit)
EXEMPTION = re.compile(r"\b(zones?|ages?|aged|attain\w*|entry|entered)\b", re.I)
SHARED_CEILING = re.compile(r"\b(collectively|aggregate|in total|combined)\b", re.I)


def blanket_reason(key: str, value: str, quote: str) -> str:
    """Why a "none" or "up to the sum insured" quote doesn't prove it ("" when it does)."""
    if key in ("copay", "deductible") and value == "0" and EXEMPTION.search(quote):
        return "exemption_not_none"
    if value.split(",")[0] in ("no_limit", "up_to_si") and SHARED_CEILING.search(quote):
        return "shared_ceiling"
    return ""


def supports(quote: str, numbers: list[float]) -> bool:
    """True when every number the value relies on is written in the quote."""
    present = numbers_in(quote)
    return all(float(n) in present for n in numbers)
