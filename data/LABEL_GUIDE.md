# Label guide

How each held-out document is labelled. The labels are the answer key for the release gate, so they
are written from the document alone, before any extraction prompt exists, and never changed after a
run to match the model.

## The insured person every label assumes

Many terms depend on the plan, so every label answers for the same case:

- **Sum insured ₹5 lakh**, or the smallest sum insured of ₹5 lakh or more that the document offers
  (the label file records which one).
- **Individual cover** for one adult aged **40** at entry, with no pre-existing disease.
- **Base plan only**: no optional covers, add-ons or riders.
- Treated in a network hospital in the **same city zone the premium was paid for**, so no zone co-payment.

## Rules learned while labelling

1. **Only what the document says.** A value is labelled only when the document states it, or names the
   item in a cover clause whose only cap is the sum insured (for example "ICU charges" listed among
   in-patient expenses). Silence is `not_stated`, even when the market norm is obvious and even in a
   full policy wording: the policy schedule, which is not part of these documents, can still set a
   limit. Telling a user "no room-rent limit" when the schedule might have one is the error this
   product exists to prevent.
2. **Optional covers don't count.** A co-payment or deductible that applies only "if opted" means the
   base plan has none: label `0`, quoting the optional clause. A limit that belongs to an add-on
   (an optional cataract sub-limit, say) is not a base-plan limit.
3. **Menus become options.** When the document offers several values and the policy schedule picks one
   ("1% of sum insured OR a single private AC room OR at actuals"), the label lists them all:
   `options:no_limit|percent_si:1|single_private_room`. The product should answer "depends on your
   plan", with the options.
4. **Undecidable is skipped.** If the label assumptions can't pick between plan-dependent values that
   are not offered as a menu, the term is labelled `skip` and left out of scoring, with the reason.
5. **A default counts.** "'At Actuals' unless otherwise specified in the Policy Schedule" is labelled
   with its default (`no_limit`).

## Values

| Term | Canonical values | Notes |
| --- | --- | --- |
| `room_rent` | `no_limit`, `single_private_room`, `shared_room`, `percent_si:<p>`, `percent_si:<p>,cap:<₹>`, `amount:<₹>` | Per day |
| `icu` | `no_limit`, `percent_si:<p>`, `percent_si:<p>,cap:<₹>`, `amount:<₹>` | Per day |
| `copay` | `0`, `<p>` | Co-payment on every claim regardless of age, for the assumed insured |
| `copay_senior` | `<p>,age:<n>` | Co-payment triggered by age; `<n>` is the youngest entry age it applies to ("61 years and above" is 61, "above 60" is 61) |
| `deductible` | `0`, `<₹>` | Base plan |
| `initial_waiting_days` | `<days>` | For illness other than accidents |
| `ped_waiting_months` | `<months>` | Pre-existing diseases |
| `specific_waiting_months` | `<m>` or `<m1>,<m2>,...` | Every period the specific-illness clause lists, in months (90 days = 3), compared as a set |
| `maternity` | `not_covered`, `covered,waiting:<months>` | In the base plan |
| `pre_hosp_days`, `post_hosp_days` | `<days>` | |
| `cataract` | `amount:<₹>`, `percent_si:<p>`, `percent_si:<p>,cap:<₹>` | Per eye where the document says so |
| `restoration` | `<p>` | Percentage of the sum insured restored once it is used up |
| `ncb` | `<p>,max:<p>` | Yearly increase in sum insured and its cap. Includes "loyalty" bonuses earned regardless of claims; the label note says which |
| `ambulance` | `up_to_si`, `amount:<₹>`, `percent_si:<p>` | Road ambulance, per hospitalisation |
| `modern_treatments` | `up_to_si`, `percent_si:<p>`, `amount:<₹>`, `varies` | IRDAI's list of modern treatments; `varies` when each treatment has its own cap |
| `ayush` | `not_covered`, `up_to_si`, `percent_si:<p>`, `amount:<₹>` | In-patient AYUSH treatment |

Any term can also be `not_stated` (rule 1), `options:...` (rule 3) or `skip` (rule 4).

Every label with a value carries the **exact quote** that supports it and the **PDF page number**
(1 = the first page of the file, not the number printed on the page). `python -m eval.check_labels`
confirms each quote is on its page, comparing letters and digits only, because extracted PDF text often
drops spaces or uses ligatures.

## Scoring

- **Correct**: the system shows the same canonical value (for `options`, the same set of options).
- **Wrong**: the system shows a different value, or shows a value where the label is `not_stated`.
  This is the error that hurts, because a user would rely on it.
- **Withheld**: the system says "not found" or "check this yourself" where the label has a value.
  Not wrong, but not useful either. Saying "not found" where the label is `not_stated` is correct.
