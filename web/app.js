// Will My Policy Pay? — page logic. All figures come from the API; nothing is computed or invented here.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inr = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
  let current = null;          // the open card

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.");
    return data;
  }
  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const track = (event, extra = {}) => post("/api/feedback", { event, card_id: current?.card_id, ...extra }).catch(() => {});

  // ---- 1. catalogue and upload ----
  async function loadCatalogue() {
    const box = $("#catalogue");
    try {
      const items = await api("/api/catalogue");
      if (!items.length) { box.innerHTML = '<p class="muted">No ready-made cards yet. Upload your policy instead.</p>'; return; }
      box.innerHTML = items.map((e) =>
        `<button class="pick" type="button" data-id="${esc(e.id)}" aria-pressed="false"><b>${esc(e.product)}</b><span>${esc(e.insurer)} · ${esc(e.doc_type)}</span></button>`).join("");
      $$(".pick", box).forEach((b) => b.addEventListener("click", () => openCatalogue(b)));
    } catch (err) { box.innerHTML = `<p class="status err">${esc(err.message)}</p>`; }
  }

  async function openCatalogue(btn) {
    $$(".pick").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    try {
      showCard(await api(`/api/card/${encodeURIComponent(btn.dataset.id)}?age=${encodeURIComponent($("#age").value || 40)}`));
      history.replaceState(null, "", `?policy=${encodeURIComponent(btn.dataset.id)}`);
    }
    catch (err) { $("#upload-status").textContent = err.message; }
  }

  $("#upload").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#upload-btn"), status = $("#upload-status");
    btn.disabled = true; status.className = "status"; status.textContent = "Reading your policy twice and checking every quote. This takes one to two minutes.";
    try {
      const card = await api("/api/upload", { method: "POST", body: new FormData(e.target) });
      $$(".pick").forEach((b) => b.setAttribute("aria-pressed", "false"));
      status.textContent = "";
      showCard(card);
    } catch (err) { status.className = "status err"; status.textContent = err.message; }
    finally { btn.disabled = false; }
  });

  // ---- the card ----
  function termRow(t) {
    const chip = t.status === "shown" && t.watch ? '<span class="chip watch-chip">Watch out</span>'
      : t.status === "check" ? '<span class="chip check-chip">Check yourself</span>' : "";
    let src = "";
    if (t.status === "shown") {
      src = `<details class="src"><summary>Show the clause</summary><blockquote>${esc(t.quote)}<cite>Page ${esc(t.page)} of the insurer's document</cite></blockquote></details>
             <button class="wrong" type="button" data-term="${esc(t.key)}">This looks wrong</button>`;
    } else if (t.candidates?.length) {
      src = `<details class="src"><summary>What the two readings found</summary>${t.candidates.map((c) =>
        `<blockquote>${esc(c.quote)}<cite>Page ${esc(c.page)}</cite></blockquote>`).join("")}</details>`;
    }
    return `<div class="term ${esc(t.status)}"><div class="name">${esc(t.name)}</div>
      <div><div class="value">${esc(t.value)}${chip}</div><div class="meaning">${esc(t.meaning)}</div>${src}</div></div>`;
  }

  function showCard(card) {
    current = card;
    const m = card.meta, box = $("#card");
    const flag = card.flagged ? `<div class="flag"><strong>This document contains text aimed at AI tools</strong> (page ${esc(card.flagged.page)}: "${esc(card.flagged.text)}"). Every term is marked for your own check.</div>` : "";
    const watch = card.watch_outs.length ? `<div class="watch"><h3>Watch out for</h3><ol>${card.watch_outs.map((w) =>
      `<li><strong>${esc(w.name)}:</strong> ${esc(w.value)}</li>`).join("")}</ol></div>` : "";
    box.innerHTML = `
      <div class="schedule">
        <div><span>Policy</span>${esc(m.product)}</div>
        <div><span>Insurer</span>${esc(m.insurer || "From your upload")}</div>
        <div><span>Read for</span>Sum insured ${esc(m.sum_insured_text)}, age ${esc(m.age)}</div>
        <div><span>Document</span>${esc(m.doc_type || "PDF")}${m.uin ? " · " + esc(m.uin) : ""} · ${esc(m.pages)} pages</div>
      </div>
      ${flag}${watch}
      <p class="muted small">${card.counts.shown} terms confirmed from the document, ${card.counts.not_found} not in it, ${card.counts.check} to check yourself. Open "Show the clause" to see the exact words.</p>
      ${card.groups.map((g) => `<div class="group"><h3>${esc(g.title)}</h3>${g.terms.map(termRow).join("")}</div>`).join("")}
      <div class="ask"><strong>Did you learn something about this policy you didn't know?</strong>
        <div class="btns"><button class="btn" type="button" data-fb="learned_yes">Yes</button><button class="btn ghost" type="button" data-fb="learned_no">No</button>
        <button class="btn ghost" type="button" data-fb="decision_changed">It changed what I'll do</button></div><p class="muted small" id="fb-thanks" role="status"></p></div>`;
    box.hidden = false;
    $$("[data-fb]", box).forEach((b) => b.addEventListener("click", () => { track(b.dataset.fb); $("#fb-thanks").textContent = "Thank you."; }));
    $$(".wrong", box).forEach((b) => b.addEventListener("click", () => { track("term_wrong", { term: b.dataset.term }); b.textContent = "Thanks, we'll check this one."; b.disabled = true; }));
    $("#sim-policy").textContent = `Using ${m.product}, sum insured ${m.sum_insured_text}. Change the figures to match your hospital's estimate.`;
    $("#cat-wrap").hidden = !["single_private_room", "shared_room"].includes(card.calc.room);
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---- 2. simulator ----
  const PRESETS = {
    "Knee replacement": { days: 5, room_rate: 8000, icu_days: 0, doctor_ot: 120000, medicines: 60000, diagnostics: 20000, implants: 100000, non_medical: 6000, pre_post: 5000 },
    "Dengue, 4 days": { days: 4, room_rate: 5000, icu_days: 0, doctor_ot: 15000, medicines: 25000, diagnostics: 18000, implants: 0, non_medical: 3000, pre_post: 3000 },
    "Cataract, one eye": { days: 0, room_rate: 0, icu_days: 0, doctor_ot: 25000, medicines: 3000, diagnostics: 2000, implants: 20000, non_medical: 1000, pre_post: 2000, cataract: true },
    "C-section": { days: 4, room_rate: 6000, icu_days: 0, doctor_ot: 60000, medicines: 25000, diagnostics: 8000, implants: 0, non_medical: 4000, pre_post: 0 },
    "Angioplasty with ICU": { days: 2, room_rate: 7000, icu_days: 2, icu_rate: 15000, doctor_ot: 100000, medicines: 40000, diagnostics: 25000, implants: 50000, non_medical: 5000, pre_post: 5000 },
  };
  const presetBox = $("#presets");
  presetBox.innerHTML = Object.keys(PRESETS).map((k) => `<button type="button" aria-pressed="${k === "Knee replacement"}">${esc(k)}</button>`).join("");
  $$("button", presetBox).forEach((b) => b.addEventListener("click", () => {
    $$("button", presetBox).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const p = PRESETS[b.textContent], f = $("#bill");
    for (const [k, v] of Object.entries(p)) { if (f.elements[k] && f.elements[k].type !== "checkbox") f.elements[k].value = v; }
    f.elements.cataract.checked = !!p.cataract;
    if (!p.icu_days) f.elements.icu_days.value = 0;
  }));

  $("#bill").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, out = $("#result");
    if (!current) { out.hidden = false; out.innerHTML = '<p class="status err">Open a policy in step 1 first.</p>'; return; }
    const num = (n) => Number(f.elements[n].value || 0);
    const bill = { days: num("days"), room_rate: num("room_rate"), icu_days: num("icu_days"), icu_rate: num("icu_rate"),
      doctor_ot: num("doctor_ot"), medicines: num("medicines"), diagnostics: num("diagnostics"), implants: num("implants"),
      non_medical: num("non_medical"), pre_post: num("pre_post"), differential_billing: f.elements.differential_billing.checked,
      procedure: f.elements.cataract.checked ? "cataract" : "other", eyes: Number(f.elements.eyes.value) };
    if (!$("#cat-wrap").hidden) bill.category_rate = num("category_rate");
    try {
      const r = await post("/api/simulate", { calc: current.calc, sum_insured: current.meta.sum_insured, age: current.meta.age, bill, card_id: current.card_id });
      const saving = r.saving_if_within_limit ? `<p class="saving">Choose a room within your limit (${inr(r.room_limit_rate)} a day) and you pay <strong>${inr(r.saving_if_within_limit)} less</strong>.</p>` : "";
      out.innerHTML = `
        <div class="totals"><div><span>Hospital bill</span><b>${inr(r.billed)}</b></div>
          <div class="pays"><span>Policy pays</span><b>${inr(r.insurer)}</b></div><div class="you"><span>You pay</span><b>${inr(r.you)}</b></div></div>
        ${saving}
        <div class="table-wrap"><table><thead><tr><th>Item</th><th class="num">Billed</th><th class="num">Policy pays</th><th class="num">You pay</th></tr></thead><tbody>
          ${r.lines.map((l) => `<tr><td>${esc(l.item)}${l.reason ? `<span class="why">${esc(l.reason)}</span>` : ""}</td><td class="num">${inr(l.billed)}</td><td class="num pays">${inr(l.pays)}</td><td class="num you">${inr(l.you)}</td></tr>`).join("")}
          ${r.adjustments.map((a) => `<tr><td>${esc(a.item)}<span class="why">${esc(a.reason)}</span></td><td class="num"></td><td class="num pays">−${inr(a.amount)}</td><td class="num you">+${inr(a.amount)}</td></tr>`).join("")}
        </tbody></table></div>
        ${r.caveats.map((c) => `<p class="caveat">${esc(c)}</p>`).join("")}
        <p class="caveat">An estimate from the limits on the card; the claim depends on the full policy, the hospital's bill and the insurer's assessment.</p>`;
      out.hidden = false;
    } catch (err) { out.hidden = false; out.innerHTML = `<p class="status err">${esc(err.message)}</p>`; }
  });

  // ---- 3. letter ----
  $("#letter").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    const today = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
    $("#letter-text").textContent =
`To: The Grievance Redressal Officer, ${v.insurer}
Date: ${today}

Subject: Request to review the deduction on claim ${v.claim}, policy ${v.policy}

Dear Sir or Madam,

My claim ${v.claim} under policy ${v.policy} was settled with a deduction of ${inr(Number(v.amount))}. The reason given was: "${v.reason}".

I ask you to review this deduction, because: ${v.grounds}

Under the IRDAI Master Circular on Health Insurance (29 May 2024, para 17b), please also share the specific policy terms and conditions relied on for each deduction.

Please reconsider the claim and pay the amount deducted. If I don't receive a satisfactory reply within 30 days, I will take the complaint to IRDAI's Bima Bharosa portal and the Insurance Ombudsman.

Yours sincerely,
${v.name}`;
    $("#letter-out").hidden = false;
  });
  $("#copy-letter").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#letter-text").textContent); $("#copy-status").textContent = "Copied."; }
    catch { $("#copy-status").textContent = "Select the text above and copy it."; }
  });

  // ---- links: ?policy=<id> opens a card, &bill=<preset> runs a sample bill ----
  async function fromLink() {
    await loadCatalogue();
    const q = new URLSearchParams(location.search), id = q.get("policy");
    const btn = id && $(`.pick[data-id="${CSS.escape(id)}"]`);
    if (!btn) return;
    await openCatalogue(btn);
    const preset = { knee: "Knee replacement", dengue: "Dengue, 4 days", cataract: "Cataract, one eye", csection: "C-section", angioplasty: "Angioplasty with ICU" }[q.get("bill")];
    if (preset) {
      $$("button", presetBox).find((b) => b.textContent === preset)?.click();
      $("#bill").requestSubmit();
    }
  }
  fromLink();
})();
