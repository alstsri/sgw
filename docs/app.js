// SGW Hunt — static viewer. Reads docs/data/<person>.json produced by export_viewer.py.
const PEOPLE = [
  { key: "adam", label: "Adam" },
  { key: "marissa", label: "Marissa" },
];

const state = { person: PEOPLE[0].key, rec: "all", data: null };
const $ = (s) => document.querySelector(s);

function fmtCountdown(endIso) {
  if (!endIso) return { text: "", soon: false, ended: true };
  const end = new Date(endIso.replace(" ", "T"));
  const ms = end - new Date();
  if (isNaN(end)) return { text: "", soon: false, ended: false };
  if (ms <= 0) return { text: "ended", soon: false, ended: true };
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  let text = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { text: text + " left", soon: ms < 86400000, ended: false };
}

function card(item) {
  const cd = fmtCountdown(item.end_time);
  const a = document.createElement("a");
  a.className = "card";
  a.href = item.url;
  a.target = "_blank";
  a.rel = "noopener";
  const price = item.price != null ? `$${item.price}` : "—";
  const size = item.size && item.size !== "not verified" ? item.size : "";
  a.innerHTML = `
    <div class="imgwrap">
      <img loading="lazy" src="${item.image}" alt="" onerror="this.parentElement.parentElement.remove()" />
      <span class="badge ${item.rec}" data-m="${item.rec}">${item.rec === "Need measurements" ? "measure" : item.rec}</span>
      <span class="score">${Number(item.score).toFixed(1)}</span>
      <span class="countdown ${cd.soon ? "soon" : ""}">${cd.text}</span>
    </div>
    <div class="body">
      <div class="title">${item.title}</div>
      <div class="row"><span class="price">${price}</span><span class="bids">${item.bids || 0} bid${item.bids === 1 ? "" : "s"}</span></div>
      ${size ? `<div class="size">${size}</div>` : ""}
    </div>`;
  return a;
}

function render() {
  const grid = $("#grid");
  grid.innerHTML = "";
  if (!state.data) { grid.innerHTML = '<div class="empty">Loading…</div>'; return; }
  let items = state.data.items.slice();
  // Hide already-ended listings
  items = items.filter((it) => !fmtCountdown(it.end_time).ended);
  if (state.rec !== "all") items = items.filter((it) => it.rec === state.rec);
  $("#meta").textContent = `${items.length} live · swept from ${state.data.source_run}`;
  if (!items.length) { grid.innerHTML = '<div class="empty">No live items in this filter.</div>'; return; }
  for (const it of items) grid.appendChild(card(it));
}

async function load(person) {
  state.person = person;
  state.data = null;
  render();
  try {
    const res = await fetch(`data/${person}.json?t=${Date.now()}`);
    state.data = await res.json();
  } catch (e) {
    state.data = { items: [], source_run: "—" };
  }
  render();
}

function buildTabs() {
  const tabs = $("#tabs");
  PEOPLE.forEach((p) => {
    const b = document.createElement("button");
    b.textContent = p.label;
    if (p.key === state.person) b.className = "active";
    b.onclick = () => {
      tabs.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      load(p.key);
    };
    tabs.appendChild(b);
  });
}

$("#filters").addEventListener("click", (e) => {
  if (e.target.tagName !== "BUTTON") return;
  $("#filters").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
  e.target.classList.add("active");
  state.rec = e.target.dataset.rec;
  render();
});

buildTabs();
load(state.person);
// Refresh countdowns every minute
setInterval(render, 60000);
