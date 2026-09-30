/* Attesta front end — vanilla JS, no build step. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  view: "ledger", profile: null, fit: null, researchers: null, panel: null,
  selected: [], professor: "", interest: "", draftKind: "cover_letter", draft: null, pipeline: null, statuses: [],
  editingEntry: null, editingEv: null, scholarMode: "topic",
};

/* ---------------- storage (per-viewer convenience only) ---------------- */
const store = {
  get(k, d) { try { const v = localStorage.getItem("attesta:" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("attesta:" + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

/* ---------------- api / feedback ---------------- */
async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers = { "Content-Type": "application/json" };
    delete init.json;
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map(x => x.msg).join("; ") : d || `Request failed (${r.status})`);
  }
  return data;
}
let toastT;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "show" + (err ? " err" : "");
  clearTimeout(toastT); toastT = setTimeout(() => (t.className = ""), err ? 4200 : 2400);
}
async function busy(btn, label, fn) {
  const old = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>${label}`;
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.innerHTML = old; }
}

/* ---------------- theme ---------------- */
function setTheme(t) { document.documentElement.dataset.theme = t; store.set("theme", t); }
setTheme(store.get("theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
$("#themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

/* ---------------- navigation ---------------- */
function go(view) {
  S.view = view; store.set("view", view);
  $$("#chapters button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  if (view === "pipeline") loadPipeline();
  if (view === "studio") renderStudioContext();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$$("#chapters button").forEach(b => (b.onclick = () => go(b.dataset.view)));

/* ---------------- tooltips for evidence / paper ids ---------------- */
const tip = $("#tip");
function sourceText(id) {
  if (S.draft?.sources?.[id]) {
    const s = S.draft.sources[id];
    return s.type === "paper" ? `<b>${id}</b> ${esc(s.title)} (${s.year || "n.d."})` : `<b>${id}</b> ${esc(s.text)}`;
  }
  const e = S.profile?.evidence.find(x => x.id === id);
  return e ? `<b>${id}</b> ${esc(e.text)}` : "";
}
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]");
  if (!el) { tip.hidden = true; return; }
  const html = sourceText(el.dataset.tip);
  if (!html) return;
  tip.innerHTML = html; tip.hidden = false;
  const r = el.getBoundingClientRect();
  const x = Math.min(r.left, innerWidth - 336);
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = (r.bottom + 8 + tip.offsetHeight > innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8) + "px";
});
const idTag = id => `<span class="tag-id ${id.startsWith("P") ? "p" : ""}" data-tip="${id}">${id}</span>`;

/* ======================================================================
   I. LEDGER
   ====================================================================== */
async function loadProfile() {
  S.profile = await api("/api/profile");
  renderLedger();
}
function renderLedger() {
  const p = S.profile, has = p && p.evidence.length;
  $("#ledgerEmpty").hidden = !!has;
  $("#ledgerFull").hidden = !has;
  $("#ledgerActions").hidden = !has;
  if (!has) return;
  const shown = p.skills.filter(s => s.demonstrated).length;
  const sections = [...new Set(p.evidence.map(e => e.section))];
  $("#ledgerStats").innerHTML = [
    [p.evidence.length, "evidence items"], [shown, "skills shown in work"],
    [p.skills.length - shown, "skills only listed"], [sections.length, "sections"],
  ].map(([v, l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  const cats = {};
  p.skills.forEach(s => (cats[s.category] ||= []).push(s));
  $("#skillCloud").innerHTML = Object.entries(cats).map(([c, list]) => `
    <div class="skill-cat"><div class="cat">${esc(c)}</div><div class="chips">
      ${list.map(s => `<span class="chip ${s.demonstrated ? "solid" : "outline"}" title="${s.ids.join(", ")}">${esc(s.name)}</span>`).join("")}
    </div></div>`).join("") || `<p class="muted">No recognised skills yet.</p>`;

  const bySec = {};
  p.evidence.forEach(e => (bySec[e.section] ||= []).push(e));
  const icon = {
    edit: `<svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>`,
    del: `<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>`,
  };
  $("#ledgerList").innerHTML = `<p class="muted small" style="margin-bottom:14px">Source: ${esc(p.source)}${p.display ? " · " + esc(p.display) : ""}</p>` +
    Object.entries(bySec).map(([sec, items]) => `
    <div class="ledger-section"><h3>${esc(sec)} <small>${items.length}</small></h3>
      ${items.map(e => `<div class="ev-row">
        <div>${idTag(e.id)}</div>
        <div>${e.context ? `<div class="ctx">${esc(e.context)}</div>` : ""}<div class="txt">${esc(e.text)}</div>
          ${e.skills.length ? `<div class="sk">${e.skills.map(s => `<span class="chip ${e.demonstrated ? "solid" : "outline"}">${esc(s)}</span>`).join("")}</div>` : ""}
        </div>
        <div class="ev-actions"><button title="Edit" data-edit="${e.id}">${icon.edit}</button><button title="Delete" data-del="${e.id}">${icon.del}</button></div>
      </div>`).join("")}
    </div>`).join("");
  $$("[data-edit]").forEach(b => (b.onclick = () => openEvidence(b.dataset.edit)));
  $$("[data-del]").forEach(b => (b.onclick = () => deleteEvidence(b.dataset.del)));
}
async function uploadResume(file) {
  const fd = new FormData(); fd.append("file", file);
  const drop = $("#resumeDrop strong"); const old = drop.textContent;
  drop.textContent = "Reading " + file.name + "…";
  try {
    S.profile = await api("/api/profile/upload", { method: "POST", body: fd });
    renderLedger(); toast(`Ledger built: ${S.profile.evidence.length} evidence items`);
  } catch (e) { toast(e.message, true); } finally { drop.textContent = old; $("#resumeFile").value = ""; }
}
const drop = $("#resumeDrop");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", e => e.dataTransfer.files[0] && uploadResume(e.dataTransfer.files[0]));
$("#resumeFile").onchange = e => e.target.files[0] && uploadResume(e.target.files[0]);
$("#pasteResumeBtn").onclick = e => busy(e.target, "Building…", async () => {
  S.profile = await api("/api/profile/text", { method: "POST", json: { text: $("#resumePaste").value } });
  renderLedger(); toast(`Ledger built: ${S.profile.evidence.length} evidence items`);
});
$("#sampleProfileBtn").onclick = async () => {
  try { S.profile = await api("/api/profile/sample", { method: "POST" }); renderLedger(); toast("Loaded the fictional sample profile"); }
  catch (e) { toast(e.message, true); }
};
$("#replaceResumeBtn").onclick = () => { $("#ledgerEmpty").hidden = false; $("#ledgerEmpty").scrollIntoView({ behavior: "smooth" }); };

async function saveProfile(evidence) {
  S.profile = await api("/api/profile", { method: "PUT", json: { name: S.profile.name, evidence } });
  renderLedger();
}
function openEvidence(id) {
  S.editingEv = id;
  const e = id ? S.profile.evidence.find(x => x.id === id) : { section: "Experience", context: "", text: "" };
  $("#evDlgTitle").textContent = id ? `Edit ${id}` : "Add evidence";
  $("#evSection").value = e.section; $("#evContext").value = e.context; $("#evText").value = e.text;
  $("#evDlg").showModal();
}
$("#addEvidenceBtn").onclick = () => openEvidence(null);
$("#evCancel").onclick = () => $("#evDlg").close();
$("#evSave").onclick = async () => {
  const item = { section: $("#evSection").value, context: $("#evContext").value.trim(), text: $("#evText").value.trim() };
  if (item.text.length < 3) return toast("Write a statement first.", true);
  const ev = S.profile.evidence.map(({ id, section, context, text }) => ({ id, section, context, text }));
  if (S.editingEv) Object.assign(ev.find(x => x.id === S.editingEv), item); else ev.push(item);
  try { await saveProfile(ev); $("#evDlg").close(); toast("Ledger updated — IDs renumbered"); } catch (e) { toast(e.message, true); }
};
async function deleteEvidence(id) {
  const ev = S.profile.evidence.filter(x => x.id !== id).map(({ id, section, context, text }) => ({ id, section, context, text }));
  if (!ev.length) return toast("The ledger needs at least one item.", true);
  try { await saveProfile(ev); toast(`${id} removed`); } catch (e) { toast(e.message, true); }
}

/* ======================================================================
   II. JOB FIT
   ====================================================================== */
const LEVEL_COLORS = { Strong: "var(--accent)", Good: "#3f8a5c", Partial: "var(--amber)", Weak: "#b8672f", "No Evidence": "var(--seal)", Verify: "var(--gap)" };
const KIND_LABEL = { required: "Required qualifications", duty: "Duties", preferred: "Preferred qualifications", eligibility: "Eligibility — verify yourself" };

$("#sampleJobBtn").onclick = async () => {
  const { text } = await api("/api/samples/job");
  $("#fitPosting").value = text; $("#fitOrg").value = "Library Data Services"; $("#fitTitle").value = "";
};
$("#fitForm").onsubmit = e => {
  e.preventDefault();
  busy($("#fitBtn"), "Analyzing…", async () => {
    S.fit = await api("/api/fit", { method: "POST", json: { posting: $("#fitPosting").value, title: $("#fitTitle").value, org: $("#fitOrg").value } });
    renderFit(); renderStudioContext();
    $("#fitResult").scrollIntoView({ behavior: "smooth", block: "start" });
  });
};
function renderFit() {
  const f = S.fit; if (!f?.report) return;
  const r = f.report;
  const cls = /AGGRESSIVELY|^APPLY$/.test(r.recommendation) ? "go" : r.recommendation === "STRETCH" ? "mid" : "no";
  const total = Object.values(r.counts).reduce((a, b) => a + b, 0) || 1;
  const bar = Object.entries(r.counts).filter(([, n]) => n).map(([l, n]) => `<i style="width:${100 * n / total}%;background:${LEVEL_COLORS[l]}" title="${l}: ${n}"></i>`).join("");
  const legend = Object.entries(r.counts).filter(([, n]) => n).map(([l, n]) => `<span style="--c:${LEVEL_COLORS[l]}">${l} ${n}</span>`).join("");
  const groups = ["required", "duty", "preferred", "eligibility"].map(k => {
    const ms = r.matches.filter(m => m.kind === k);
    if (!ms.length) return "";
    return `<div class="req-group"><h4>${KIND_LABEL[k]}</h4>${ms.map(m => `
      <div class="req L-${m.level.replace(" ", "")}">
        <div><div class="t">${esc(m.text)}</div><div class="note">${esc(m.note)}</div>
          ${m.missing?.length ? `<div class="miss">Missing: ${m.missing.map(esc).join(", ")}</div>` : ""}</div>
        <span class="lvl">${m.level}</span>
        <div class="evs">${m.evidence.map(idTag).join("") || `<span class="muted small">—</span>`}</div>
      </div>`).join("")}</div>`;
  }).join("");
  $("#fitResult").innerHTML = `
    <div class="card verdict">
      <div class="score">${r.score}<small>/100</small></div>
      <div>
        <div class="stamp ${cls}">${esc(r.recommendation)}</div>
        <div class="reason">${esc(r.reason)}</div>
        <div class="levels-bar">${bar}</div><div class="levels-legend">${legend}</div>
      </div>
    </div>
    <div class="fit-actions">
      <button class="btn" id="toCover">Draft cover letter →</button>
      <button class="btn ghost" id="toBullets">Tailor resume bullets →</button>
      <button class="btn ghost" id="fitToPipe">Add to pipeline</button>
    </div>
    <p class="muted small">${esc(f.title || "Untitled role")}${f.org ? " · " + esc(f.org) : ""} — hover an evidence ID to read it.</p>
    ${r.listed_not_shown?.length ? `<p class="small" style="margin-top:8px;color:var(--amber)">Listed but never shown in your work: ${r.listed_not_shown.map(esc).join(", ")}. A professor may ask where you used these.</p>` : ""}
    ${groups}`;
  $("#toCover").onclick = () => { setKind("cover_letter"); go("studio"); generate(); };
  $("#toBullets").onclick = () => { setKind("resume_bullets"); go("studio"); generate(); };
  $("#fitToPipe").onclick = () => addToPipeline({ kind: "job", title: f.title || "Untitled role", org: f.org, fit_score: r.score });
}

/* ======================================================================
   III. SCHOLARS
   ====================================================================== */
$$("#scholarMode button").forEach(b => (b.onclick = () => {
  S.scholarMode = b.dataset.mode;
  $$("#scholarMode button").forEach(x => x.classList.toggle("active", x === b));
  $("#topicForm").hidden = S.scholarMode !== "topic";
  $("#nameForm").hidden = S.scholarMode !== "name";
}));
const skeletons = n => Array(n).fill('<div class="skeleton"></div>').join("");

$("#topicForm").onsubmit = e => {
  e.preventDefault();
  const topic = $("#topicInput").value.trim();
  S.interest = topic;
  $("#scholarResults").innerHTML = skeletons(4); closePanel();
  busy($("#topicForm .btn"), "Searching…", async () => {
    const res = await api("/api/research/topic", { method: "POST", json: { topic, affiliation: $("#affInput").value, include_unknown: $("#includeUnknown").checked } });
    S.researchers = res;
    $("#scholarNote").textContent = `Source: ${res.source} · ${res.papersScanned} papers scanned${res.note ? " · " + res.note : ""}`;
    renderResearchers();
  }).then(() => { if (!S.researchers) $("#scholarResults").innerHTML = ""; });
};
function renderResearchers() {
  const list = S.researchers?.researchers || [];
  if (!list.length) {
    $("#scholarResults").innerHTML = `<div class="empty-note"><p>No researchers matched. Try a broader topic, or tick “include unknown affiliation”.</p></div>`;
    return;
  }
  $("#scholarResults").innerHTML = list.map((r, i) => `
    <div class="card researcher" data-i="${i}">
      <div class="rank">${i + 1}</div>
      <div>
        <div class="name">${esc(r.name)}</div>
        <div class="aff">${esc((r.affiliations || []).join(" · ") || "Affiliation not listed")}${r.hIndex != null ? ` · h-index ${r.hIndex}` : ""}</div>
        <div class="meter"><div class="track"><i style="width:${r.match}%"></i></div>${r.match}% topic match · ${r.matchedPapers} matching paper${r.matchedPapers > 1 ? "s" : ""}</div>
        <ul>${r.papers.map(p => `<li><b>${p.year || "—"}</b>${esc(p.title)}</li>`).join("")}</ul>
        ${r.sharedGround?.length ? `<div class="ground">Closest evidence of yours: ${r.sharedGround.map(g => idTag(g.id)).join("")}</div>` : ""}
      </div>
    </div>`).join("");
  $$(".researcher").forEach(el => (el.onclick = () => {
    $$(".researcher").forEach(x => x.classList.toggle("sel", x === el));
    openResearcher(list[+el.dataset.i]);
  }));
}
$("#nameForm").onsubmit = e => {
  e.preventDefault();
  const q = $("#nameInput").value.trim();
  S.interest = $("#nameTopic").value.trim() || S.interest;
  $("#scholarResults").innerHTML = skeletons(3); closePanel();
  busy($("#nameForm .btn"), "Searching…", async () => {
    const { authors } = await api("/api/research/authors?q=" + encodeURIComponent(q));
    $("#scholarNote").textContent = `Source: Semantic Scholar · ${authors.length} author profile${authors.length === 1 ? "" : "s"} — several people can share a name; check affiliation and paper count.`;
    $("#scholarResults").innerHTML = authors.length ? authors.map((a, i) => `
      <div class="card author-row" data-i="${i}">
        <div><div class="name" style="font-family:var(--serif);font-size:18px;font-weight:600">${esc(a.name)}</div>
        <div class="aff muted small">${esc(a.affiliations.join(" · ") || "Affiliation not listed")}</div></div>
        <div class="muted small" style="text-align:right">${a.paperCount ?? "?"} papers<br>h-index ${a.hIndex ?? "?"}</div>
      </div>`).join("") : `<div class="empty-note"><p>No author profiles found for that name.</p></div>`;
    $$(".author-row").forEach(el => (el.onclick = () => openResearcher({ ...authors[+el.dataset.i], papers: null })));
  });
};
function closePanel() { $("#paperPanel").hidden = true; $(".scholar-grid").classList.remove("with-panel"); }
async function openResearcher(r) {
  const panel = $("#paperPanel");
  panel.hidden = false; $(".scholar-grid").classList.add("with-panel");
  panel.innerHTML = `<h3>${esc(r.name)}</h3><p class="muted small">${esc((r.affiliations || []).join(" · "))}</p>${skeletons(3)}`;
  let papers = r.papers || [], ground = r.sharedGround || [];
  if (r.authorId) {
    try {
      const res = await api(`/api/research/authors/${encodeURIComponent(r.authorId)}/papers?topic=${encodeURIComponent(S.interest || "")}`);
      papers = res.papers; ground = res.sharedGround;
    } catch (e) { toast(e.message, true); }
  }
  S.panel = { author: r, papers, ground };
  S.professor = r.name;
  S.selected = S.selected.filter(p => papers.some(x => x.paperId === p.paperId));
  renderPanel();
}
function renderPanel() {
  const { author, papers, ground } = S.panel;
  const isSel = p => S.selected.some(x => x.paperId === p.paperId);
  $("#paperPanel").innerHTML = `
    <h3>${esc(author.name)}</h3>
    <p class="muted small">${esc((author.affiliations || []).join(" · ") || "Affiliation not listed")}${author.url ? ` · <a href="${esc(author.url)}" target="_blank" rel="noopener">profile ↗</a>` : ""}</p>
    ${ground.length ? `<div class="ground" style="margin:10px 0 4px">Your closest evidence: ${ground.map(g => idTag(g.id)).join("")}</div>` : ""}
    <p class="small" style="margin:12px 0 4px"><b>Select up to 3 papers</b> to reference in your email.</p>
    ${papers.length ? papers.map((p, i) => `
      <label class="paper"><input type="checkbox" data-p="${i}" ${isSel(p) ? "checked" : ""}>
        <div><div class="pt">${esc(p.title)}</div>
          <div class="pm">${p.year || "n.d."}${p.venue ? " · " + esc(p.venue) : ""}${p.citations != null ? ` · ${p.citations} citations` : ""}${p.overlap >= 0.08 ? " · strong link to your ledger" : p.overlap >= 0.03 ? " · some link to your ledger" : ""}</div>
          ${p.snippet ? `<div class="ps">${esc(p.snippet)}</div>` : `<div class="ps muted">No abstract available.</div>`}
          ${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">Open paper ↗</a>` : ""}</div>
      </label>`).join("") : `<p class="muted">No papers found for this author.</p>`}
    <div class="panel-foot">
      <label>Your research interest (used in the email)<input id="interestIn" value="${esc(S.interest)}" placeholder="e.g. clinical NLP"></label>
      <button class="btn" id="toOutreach" ${S.selected.length ? "" : "disabled"}>Draft outreach email (${S.selected.length}) →</button>
    </div>`;
  $$("#paperPanel [data-p]").forEach(cb => (cb.onchange = () => {
    const p = papers[+cb.dataset.p];
    if (cb.checked) {
      if (S.selected.length >= 3) { cb.checked = false; return toast("Pick at most 3 papers — specificity beats volume.", true); }
      S.selected.push(p);
    } else S.selected = S.selected.filter(x => x.paperId !== p.paperId);
    persistResearch(); renderPanel();
  }));
  $("#interestIn").oninput = e => { S.interest = e.target.value; persistResearch(); };
  $("#toOutreach").onclick = () => { setKind("outreach_email"); go("studio"); generate(); };
}
function persistResearch() { store.set("research", { selected: S.selected, professor: S.professor, interest: S.interest }); }

/* ======================================================================
   IV. STUDIO
   ====================================================================== */
function setKind(k) {
  S.draftKind = k; store.set("kind", k);
  $$("#draftKind button").forEach(b => b.classList.toggle("active", b.dataset.kind === k));
  renderStudioContext();
}
$$("#draftKind button").forEach(b => (b.onclick = () => setKind(b.dataset.kind)));
function renderStudioContext() {
  const el = $("#studioContext");
  if (S.draftKind === "outreach_email") {
    el.innerHTML = S.selected.length
      ? `To <b>Professor ${esc(S.professor)}</b> · ${S.selected.length} paper${S.selected.length > 1 ? "s" : ""} selected`
      : `Pick a researcher and papers in <a href="#" class="linkish" data-go="scholars">Scholars</a> first.`;
  } else {
    el.innerHTML = S.fit?.report
      ? `For <b>${esc(S.fit.title || "the role")}</b>${S.fit.org ? " · " + esc(S.fit.org) : ""} · fit ${S.fit.report.score}`
      : `Run a <a href="#" class="linkish" data-go="fit">Job Fit</a> analysis first.`;
  }
  $$("[data-go]", el).forEach(a => (a.onclick = e => { e.preventDefault(); go(a.dataset.go); }));
}
$("#generateBtn").onclick = () => generate();
function generate() {
  const body = { kind: S.draftKind, papers: S.selected, professor: S.professor, interest: S.interest };
  $("#sheet").innerHTML = `<div class="skeleton" style="height:60px"></div>${skeletons(3)}`;
  return busy($("#generateBtn"), "Writing & verifying…", async () => {
    S.draft = await api("/api/drafts", { method: "POST", json: body });
    store.set("draft", S.draft);
    renderDraft();
  }).then(() => { if (!S.draft || S.draft.kind !== S.draftKind) renderDraft(); });
}
function sentenceHtml(s, i) {
  const cites = s.cites.map(c => `<sup class="cite ${c.startsWith("P") ? "p" : ""}">${c}</sup>`).join("");
  return `<span class="s ${s.status}" data-i="${i}">${esc(s.clean)}${cites}</span>`;
}
function renderDraft() {
  const d = S.draft;
  $("#editor").hidden = true;
  if (!d) {
    $("#sheetTools").hidden = true;
    $("#sheet").innerHTML = `<div class="empty-note"><p>Run a Job Fit analysis or pick papers in Scholars, then generate a draft.</p></div>`;
    $("#provenance").innerHTML = `<h3>Provenance</h3><p class="muted">Hover or tap any sentence to see where it comes from.</p>`;
    return;
  }
  $("#sheetTools").hidden = false;
  const sents = d.verification.sentences;
  const paras = [];
  sents.forEach((s, i) => { (paras[s.paragraph] ||= []).push([s, i]); });
  const body = paras.filter(Boolean).map(ps => {
    if (ps[0][0].bullet) return `<ul>${ps.map(([s, i]) => `<li>${sentenceHtml(s, i)}</li>`).join("")}</ul>`;
    return `<p>${ps.map(([s, i]) => (s.br ? "<br>" : " ") + sentenceHtml(s, i)).join("").trim()}</p>`;
  }).join("");
  const sheet = $("#sheet");
  sheet.classList.toggle("marks", $("#marksToggle").checked);
  sheet.innerHTML = (d.subject ? `<div class="subject">Subject: <b>${esc(d.subject)}</b></div>` : "") + body;
  $$(".s", sheet).forEach(el => {
    el.onmouseenter = () => inspect(+el.dataset.i);
    el.onclick = () => { $$(".s.focus").forEach(x => x.classList.remove("focus")); el.classList.add("focus"); inspect(+el.dataset.i); };
  });
  renderProvenance();
}
const STATUS_LABEL = { attested: "Attested", warn: "Check citation", gap: "Honest gap", unsupported: "Unsupported", neutral: "No claim" };
function renderProvenance(inspectHtml = "") {
  const d = S.draft, sm = d.verification.summary;
  const engine = d.engine === "offline" ? "offline writer" : d.engine + (d.rounds > 1 ? " · repaired once" : "");
  $("#provenance").innerHTML = `
    <h3>Provenance</h3>
    ${d.note ? `<p class="engine-note">${esc(d.note)}</p>` : ""}
    <div class="integrity"><span class="v">${sm.integrity}%</span><span class="muted">of claims attested</span></div>
    <div class="tally">${["attested", "gap", "warn", "unsupported", "neutral"].map(k =>
      `<div><span><span class="st-dot st-${k}"></span>${STATUS_LABEL[k]}</span><b>${sm[k]}</b></div>`).join("")}</div>
    <p class="muted small">Written by the ${esc(engine)} · checked by the rule-based verifier.</p>
    <div class="inspect" id="inspect">${inspectHtml || `<p class="muted small">Hover a sentence to inspect it.</p>`}</div>
    ${d.struck?.length ? `<div class="struck"><h4>Struck by the verifier (${d.struck.length})</h4>
      ${d.struck.map(x => `<div class="x"><s>${esc(x.text)}</s><small>${esc(x.reasons.join(" "))}</small></div>`).join("")}</div>` : ""}`;
}
function inspect(i) {
  const s = S.draft.verification.sentences[i];
  const srcs = s.cites.map(c => {
    const x = S.draft.sources[c];
    if (!x) return `<div class="src"><div class="h">${idTag(c)} missing</div>This source does not exist.</div>`;
    return x.type === "paper"
      ? `<div class="src"><div class="h">${idTag(c)} paper · ${x.year || "n.d."}</div><b>${esc(x.title)}</b>${x.snippet ? `<div class="muted small" style="margin-top:4px">${esc(x.snippet)}</div>` : ""}</div>`
      : `<div class="src"><div class="h">${idTag(c)} ${esc(x.section)}${x.context ? " · " + esc(x.context) : ""}</div>${esc(x.text)}</div>`;
  }).join("");
  $("#inspect").innerHTML = `<div class="status"><span class="st-dot st-${s.status}"></span>${STATUS_LABEL[s.status]}</div>
    ${s.reasons.length ? `<ul>${s.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : `<p class="muted small">Greeting, intent or question — no factual claim to check.</p>`}${srcs}`;
}
$("#marksToggle").onchange = e => $("#sheet").classList.toggle("marks", e.target.checked);
$("#editBtn").onclick = () => {
  $("#editorText").value = S.draft.text;
  $("#editor").hidden = false; $("#sheet").hidden = true; $("#sheetTools").hidden = true;
  $("#editorText").focus();
};
$("#cancelEditBtn").onclick = () => { $("#editor").hidden = true; $("#sheet").hidden = false; $("#sheetTools").hidden = false; };
$("#reverifyBtn").onclick = e => busy(e.target, "Verifying…", async () => {
  const text = $("#editorText").value;
  const papers = S.draft.kind === "outreach_email" ? S.selected : [];
  const ver = await api("/api/verify", { method: "POST", json: { text, papers, allowed: S.draft.allowed || [] } });
  S.draft = { ...S.draft, text, verification: ver, struck: [] };
  store.set("draft", S.draft);
  $("#sheet").hidden = false; renderDraft();
  toast(ver.summary.unsupported ? `${ver.summary.unsupported} sentence(s) not supported — marked in red` : "Every claim checks out");
});
function cleanText() {
  const d = S.draft, paras = [];
  d.verification.sentences.forEach(s => {
    const arr = (paras[s.paragraph] ||= []);
    arr.push((s.bullet ? "- " : s.br ? "\n" : "") + s.clean);
  });
  const body = paras.filter(Boolean).map(p => p[0].startsWith("- ") ? p.join("\n") : p.join(" ").replace(/ \n/g, "\n")).join("\n\n");
  return (d.subject ? `Subject: ${d.subject}\n\n` : "") + body;
}
$("#copyBtn").onclick = async () => {
  const txt = cleanText();
  try { await navigator.clipboard.writeText(txt); }
  catch { const t = document.createElement("textarea"); t.value = txt; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
  const bad = S.draft.verification.summary.unsupported;
  toast(bad ? `Copied — but ${bad} unsupported sentence(s) are still in it` : "Copied without citation marks");
};
$("#saveDraftBtn").onclick = () => {
  const d = S.draft;
  if (d.kind === "outreach_email") addToPipeline({ kind: "research", title: "Prof. " + S.professor, org: "", notes: "Outreach draft: " + (d.subject || "") });
  else addToPipeline({ kind: "job", title: S.fit?.title || "Untitled role", org: S.fit?.org || "", fit_score: S.fit?.report?.score ?? null });
};

/* ======================================================================
   V. PIPELINE
   ====================================================================== */
const STAGE = { researching: "Researching", applied: "Applied / Emailed", replied: "Replied", interview: "Interview", closed: "Closed" };
async function loadPipeline() {
  try { const r = await api("/api/pipeline"); S.pipeline = r.items; S.statuses = r.statuses; renderBoard(); }
  catch (e) { toast(e.message, true); }
}
function renderBoard() {
  const today = new Date().toISOString().slice(0, 10);
  $("#board").innerHTML = S.statuses.map(st => {
    const items = S.pipeline.filter(x => x.status === st);
    return `<div class="col" data-st="${st}"><div class="col-h"><h4>${STAGE[st]}</h4><span>${items.length}</span></div>
      ${items.map(x => `<div class="pcard" draggable="true" data-id="${x.id}">
        <div class="k"><span>${x.kind === "job" ? "Job" : "Research"}</span>${x.fit_score != null ? `<span class="fitb">${x.fit_score}</span>` : ""}</div>
        <div class="t">${esc(x.title)}</div>${x.org ? `<div class="o">${esc(x.org)}</div>` : ""}
        <div class="f"><span class="due ${x.follow_up && x.follow_up < today && !["closed", "interview"].includes(x.status) ? "late" : ""}">${x.follow_up ? "Follow up " + x.follow_up : ""}</span></div>
      </div>`).join("")}</div>`;
  }).join("");
  $$(".pcard").forEach(c => {
    c.ondragstart = e => { e.dataTransfer.setData("text/plain", c.dataset.id); c.classList.add("dragging"); };
    c.ondragend = () => c.classList.remove("dragging");
    c.onclick = () => openEntry(S.pipeline.find(x => x.id === +c.dataset.id));
  });
  $$(".col").forEach(col => {
    col.ondragover = e => { e.preventDefault(); col.classList.add("over"); };
    col.ondragleave = () => col.classList.remove("over");
    col.ondrop = async e => {
      e.preventDefault(); col.classList.remove("over");
      const id = +e.dataTransfer.getData("text/plain"), item = S.pipeline.find(x => x.id === id);
      if (!item || item.status === col.dataset.st) return;
      item.status = col.dataset.st; renderBoard();
      try { await api(`/api/pipeline/${id}`, { method: "PATCH", json: { status: col.dataset.st } }); } catch (err) { toast(err.message, true); loadPipeline(); }
    };
  });
}
async function addToPipeline(data) {
  try { await api("/api/pipeline", { method: "POST", json: { status: "researching", ...data } }); toast("Added to pipeline"); if (S.view === "pipeline") loadPipeline(); }
  catch (e) { toast(e.message, true); }
}
function openEntry(x) {
  S.editingEntry = x?.id ?? null;
  $("#entryTitle").textContent = x ? "Edit entry" : "New entry";
  $("#eStatus").innerHTML = (S.statuses.length ? S.statuses : Object.keys(STAGE)).map(s => `<option value="${s}">${STAGE[s]}</option>`).join("");
  $("#eKind").value = x?.kind || "job"; $("#eKind").disabled = !!x;
  $("#eStatus").value = x?.status || "researching"; $("#eTitleIn").value = x?.title || ""; $("#eOrg").value = x?.org || "";
  $("#eContact").value = x?.contact || ""; $("#eFollow").value = x?.follow_up || ""; $("#eFit").value = x?.fit_score ?? "";
  $("#eLink").value = x?.link || ""; $("#eNotes").value = x?.notes || "";
  $("#deleteEntry").hidden = !x;
  $("#entryDlg").showModal();
}
$("#newEntryBtn").onclick = () => openEntry(null);
$("#cancelEntry").onclick = () => $("#entryDlg").close();
$("#saveEntry").onclick = async () => {
  const data = { title: $("#eTitleIn").value.trim(), org: $("#eOrg").value.trim(), contact: $("#eContact").value.trim(), status: $("#eStatus").value,
    follow_up: $("#eFollow").value, notes: $("#eNotes").value, link: $("#eLink").value.trim(), fit_score: $("#eFit").value === "" ? null : +$("#eFit").value };
  if (!data.title) return toast("Give it a title.", true);
  try {
    if (S.editingEntry) await api(`/api/pipeline/${S.editingEntry}`, { method: "PATCH", json: data });
    else await api("/api/pipeline", { method: "POST", json: { ...data, kind: $("#eKind").value } });
    $("#entryDlg").close(); loadPipeline();
  } catch (e) { toast(e.message, true); }
};
$("#deleteEntry").onclick = async () => {
  try { await api(`/api/pipeline/${S.editingEntry}`, { method: "DELETE" }); $("#entryDlg").close(); loadPipeline(); toast("Entry deleted"); }
  catch (e) { toast(e.message, true); }
};

/* ======================================================================
   SETTINGS
   ====================================================================== */
const ENGINE_NAME = { offline: "Offline writer", anthropic: "Claude", openai: "OpenAI", ollama: "Ollama" };
function setEngine(p) { $("#engineLabel").textContent = ENGINE_NAME[p] || p; $("#enginePill").classList.toggle("live", p !== "offline"); }
function syncProviderFields() {
  const p = $("#providerSet input:checked")?.value || "offline";
  $("#keyWrap").hidden = !["anthropic", "openai"].includes(p);
  $("#ollamaWrap").hidden = p !== "ollama";
  $("#setModel").placeholder = S.defaults?.[p] ? "default: " + S.defaults[p] : "not needed";
  $("#setModel").disabled = p === "offline";
}
async function openSettings() {
  const s = await api("/api/settings");
  S.defaults = s.default_models;
  $$("#providerSet input").forEach(r => (r.checked = r.value === s.provider));
  $("#setModel").value = s.model; $("#setKey").value = s.api_key; $("#setOllama").value = s.ollama_url; $("#setS2").value = s.s2_api_key;
  $("#testMsg").textContent = ""; syncProviderFields();
  $("#settingsDlg").showModal();
}
$$("#providerSet input").forEach(r => (r.onchange = () => { $("#setKey").value = ""; syncProviderFields(); }));
async function saveSettings() {
  const key = $("#setKey").value.trim(), s2 = $("#setS2").value.trim();
  const s = await api("/api/settings", { method: "PUT", json: {
    provider: $("#providerSet input:checked").value, model: $("#setModel").value.trim(),
    api_key: key && !key.startsWith("••") ? key : null, ollama_url: $("#setOllama").value.trim() || "http://localhost:11434",
    s2_api_key: s2 && !s2.startsWith("••") ? s2 : null } });
  setEngine(s.provider);
  return s;
}
$("#settingsBtn").onclick = openSettings;
$("#enginePill").onclick = openSettings;
$("#closeSettings").onclick = () => $("#settingsDlg").close();
$("#saveSettings").onclick = async () => { try { await saveSettings(); $("#settingsDlg").close(); toast("Settings saved"); } catch (e) { toast(e.message, true); } };
$("#testBtn").onclick = e => busy(e.target, "Testing…", async () => {
  await saveSettings();
  const r = await api("/api/settings/test", { method: "POST" });
  const m = $("#testMsg"); m.textContent = r.message; m.className = "test-msg " + (r.ok ? "ok" : "err");
});

/* ======================================================================
   BOOT
   ====================================================================== */
(async function boot() {
  const research = store.get("research", {});
  S.selected = research.selected || []; S.professor = research.professor || ""; S.interest = research.interest || "";
  setKind(store.get("kind", "cover_letter"));
  S.draft = store.get("draft", null);
  try {
    const [health, fit] = await Promise.all([api("/api/health"), api("/api/fit/last"), loadProfile()]);
    setEngine(health.provider);
    if (fit?.report) {
      S.fit = fit; renderFit();
      $("#fitTitle").value = fit.title || ""; $("#fitOrg").value = fit.org || "";
    }
  } catch (e) { toast("Can't reach the Attesta server: " + e.message, true); }
  renderDraft(); renderStudioContext();
  go(store.get("view", "ledger"));
})();
