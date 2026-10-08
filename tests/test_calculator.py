"""25 hand-worked bills. The release gate needs all 25 to match; each expected figure was worked out
by hand, not by running the calculator."""
import pytest

from fineprint.calculator import Bill, Terms, simulate

L5 = 500000

CASES = [
    # id, terms, bill, expected insurer pays, expected you pay
    ("T01 no limits", Terms(L5, "no_limit", "no_limit"),
     Bill(days=3, room_rate=4000, doctor_ot=50000, medicines=20000, diagnostics=8000, non_medical=3000), 90000, 3000),
    ("T02 room within 1% cap", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(days=3, room_rate=4000, doctor_ot=50000, medicines=20000, diagnostics=8000, non_medical=3000), 90000, 3000),
    ("T03 PRD knee replacement", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(days=5, room_rate=8000, doctor_ot=120000, medicines=60000, diagnostics=20000, implants=100000), 280000, 60000),
    ("T04 no differential billing", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(days=5, room_rate=8000, doctor_ot=120000, medicines=60000, diagnostics=20000, implants=100000, differential_billing=False), 325000, 15000),
    ("T05 ICU over cap, room within", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(days=2, room_rate=4000, icu_days=3, icu_rate=15000, doctor_ot=40000, medicines=30000), 108000, 15000),
    ("T06 ICU and room over caps", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(days=2, room_rate=8000, icu_days=3, icu_rate=15000, doctor_ot=40000, medicines=30000), 95000, 36000),
    ("T07 Arogya Sanjeevani 2% max 5000, 5% co-pay", Terms(L5, "percent_si:2,cap:5000", "percent_si:5,cap:10000", copay=5),
     Bill(days=4, room_rate=6000, doctor_ot=60000, medicines=40000), 104500, 19500),
    ("T08 senior co-pay applies", Terms(L5, "no_limit", "no_limit", copay_senior="20,age:61", age=65),
     Bill(days=3, room_rate=3000, doctor_ot=30000, medicines=21000), 48000, 12000),
    ("T09 senior co-pay doesn't apply", Terms(L5, "no_limit", "no_limit", copay_senior="20,age:61", age=40),
     Bill(days=3, room_rate=3000, doctor_ot=30000, medicines=21000), 60000, 0),
    ("T10 deductible", Terms(L5, "no_limit", "no_limit", deductible=25000),
     Bill(days=3, room_rate=3000, doctor_ot=30000, medicines=21000), 35000, 25000),
    ("T11 deductible then co-pay", Terms(L5, "no_limit", "no_limit", deductible=10000, copay=10),
     Bill(days=3, room_rate=3000, doctor_ot=30000, medicines=21000), 45000, 15000),
    ("T12 cataract ₹40,000 per eye", Terms(L5, "no_limit", "no_limit", cataract="amount:40000"),
     Bill(procedure="cataract", eyes=1, doctor_ot=30000, implants=25000, medicines=5000, diagnostics=2000), 40000, 22000),
    ("T13 cataract 20% max 50,000, two eyes", Terms(L5, "no_limit", "no_limit", cataract="percent_si:20,cap:50000"),
     Bill(procedure="cataract", eyes=2, doctor_ot=60000, implants=50000, medicines=10000), 100000, 20000),
    ("T14 cataract 25% of ₹1 lakh", Terms(100000, "no_limit", "no_limit", cataract="percent_si:25,cap:40000"),
     Bill(procedure="cataract", eyes=1, doctor_ot=25000, implants=15000, medicines=5000), 25000, 20000),
    ("T15 sum insured exhausted", Terms(300000, "no_limit", "no_limit"),
     Bill(days=10, room_rate=5000, doctor_ot=200000, medicines=100000, diagnostics=50000), 300000, 100000),
    ("T16 non-medical items", Terms(L5, "no_limit", "no_limit"),
     Bill(days=2, room_rate=3000, doctor_ot=20000, medicines=10000, non_medical=12000), 36000, 12000),
    ("T17 single private room limit, deluxe chosen", Terms(L5, "single_private_room", "no_limit"),
     Bill(days=4, room_rate=12000, category_rate=6000, doctor_ot=80000, medicines=30000, diagnostics=10000), 104000, 64000),
    ("T18 single private room taken", Terms(L5, "single_private_room", "no_limit"),
     Bill(days=4, room_rate=6000, category_rate=6000, doctor_ot=80000, medicines=30000, diagnostics=10000), 144000, 0),
    ("T19 ₹2,000 a day room limit", Terms(200000, "amount:2000", "no_limit"),
     Bill(days=3, room_rate=3000, doctor_ot=30000, medicines=15000), 41000, 13000),
    ("T20 proportionate deduction then co-pay", Terms(L5, "percent_si:1", "percent_si:2", copay=10),
     Bill(days=5, room_rate=8000, doctor_ot=120000, medicines=60000, diagnostics=20000, implants=100000), 252000, 88000),
    ("T21 pre and post hospitalisation", Terms(L5, "no_limit", "no_limit"),
     Bill(days=3, room_rate=3000, doctor_ot=20000, medicines=10000, pre_post=8000), 47000, 0),
    ("T22 room limit unknown", Terms(L5, None, None),
     Bill(days=5, room_rate=8000, doctor_ot=120000, medicines=60000, diagnostics=20000, implants=100000), 340000, 0),
    ("T23 ₹10 lakh, within both caps", Terms(1000000, "percent_si:1", "percent_si:2"),
     Bill(days=5, room_rate=9000, icu_days=2, icu_rate=18000, doctor_ot=100000, medicines=50000), 231000, 0),
    ("T24 ICU only, over cap", Terms(L5, "percent_si:1", "percent_si:2"),
     Bill(icu_days=4, icu_rate=12000, doctor_ot=60000), 100000, 8000),
    ("T25 ratio 3/7", Terms(300000, "percent_si:1", "percent_si:2"),
     Bill(days=3, room_rate=7000, doctor_ot=35000, medicines=10000, diagnostics=5000), 39000, 32000),
]


@pytest.mark.parametrize("name,terms,bill,insurer,you", CASES, ids=[c[0] for c in CASES])
def test_hand_worked_bill(name, terms, bill, insurer, you):
    r = simulate(bill, terms)
    assert (r.insurer, r.you) == (insurer, you)
    assert r.billed == r.insurer + r.you


def test_room_limit_saving_and_reasons():
    r = simulate(Bill(days=5, room_rate=8000, doctor_ot=120000, medicines=60000, diagnostics=20000, implants=100000),
                 Terms(L5, "percent_si:1", "percent_si:2"))
    assert r.saving_if_within_limit == 60000            # in a ₹5,000 room the same stay is paid in full
    reasons = " ".join(l.reason for l in r.lines)
    assert "62.5%" in reasons and "Never cut in proportion" in reasons


def test_unknown_room_limit_is_flagged():
    r = simulate(Bill(days=2, room_rate=5000, doctor_ot=10000), Terms(L5, None, None))
    assert any("wasn't found" in c for c in r.caveats)


def test_unconfirmed_copay_and_deductible_are_assumed_none_and_said():
    bill = Bill(days=4, room_rate=4000, doctor_ot=20000, medicines=10000)
    known = simulate(bill, Terms(L5, "percent_si:1", "percent_si:2"))
    unknown = simulate(bill, Terms(L5, "percent_si:1", "percent_si:2", copay=None, deductible=None))
    assert unknown.insurer == known.insurer and not known.caveats
    assert any("co-payment" in c for c in unknown.caveats) and any("deductible" in c for c in unknown.caveats)
