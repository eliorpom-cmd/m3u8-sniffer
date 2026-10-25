// Popup: popup-blocker toggle for the current site, and the tab's m3u8 streams analysed before download.
const HOST = "dev.byelior.m3u8";
const isMaster = (u) => /master|index|playlist/i.test(u.split("?")[0].split("/").pop());
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
const native = (msg) => new Promise((resolve) =>
  chrome.runtime.sendNativeMessage(HOST, msg, (res) =>
    resolve(chrome.runtime.lastError ? { error: "Hôte injoignable (" + chrome.runtime.lastError.message + ") : relance l'installeur (install-host.sh sur Mac, Installer (Windows).bat sur Windows)" } : res)));

const langNames = new Intl.DisplayNames(["fr"], { type: "language" });
const langName = (code) => {
  try { const n = langNames.of(code); return n[0].toUpperCase() + n.slice(1); } catch { return code; }
};
const isFr = (code) => /^(fr|fre|fra)\b/i.test(code || "");
const gb = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1).replace(".", ",")} Go` : `${Math.round(b / 1e6)} Mo`);
const hms = (s) => { const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`; };
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

// VF / VOSTFR / VO from the audio and subtitle languages, else from words in the page title or URL.
function version(info, hint) {
  const audio = [...info.audios.map((a) => a.lang), ...info.formats.map((f) => f.lang)].filter(Boolean);
  const fr = audio.some(isFr), other = audio.some((l) => !isFr(l)), frSub = info.subtitles.some((s) => isFr(s.lang));
  if (fr && other) return "VF + VO";
  if (fr) return "VF";
  if (other) return frSub ? "VOSTFR" : "VO";
  if (/vostfr/i.test(hint)) return "VOSTFR";
  if (/\b(true)?(vff|vfq|vf|french)\b/i.test(hint)) return "VF";
  if (/\bvo\b/i.test(hint)) return "VO";
  return null;
}

// "Regarder Dune en streaming VF - Site" → "Dune"
const cleanTitle = (t) => (t || "vidéo").split(/\s[|–—-]\s/)[0]
  .replace(/^(regarder|voir)\s+/i, "").replace(/\s+(en\s+)?(streaming|vostfr|vff?|vf|hd|gratuit)\b.*$/i, "")
  .replace(/\s*:\s*/g, " - ").replace(/[\/*?"<>|\\]/g, "").replace(/\s+/g, " ").trim().slice(0, 80) || "vidéo";

// Jellyfin layout under ~/Documents/Films: movies in Films/, episodes in Séries/<Show (Year)>/Season NN/<Show> SxxEyy.
// An episode is spotted by S01E02, 1x02, "Saison 1 Épisode 2" or a bare E02 (season 1 unless "Saison N" is in the name).
// A bare "Episode 4" or "Ep 4" is also a film's title ("Star Wars Episode 4"): it counts only with "Saison" or
// "Season" in the name or when the show already has its folder in Séries.
// \b is ASCII-only, so before "Épisode" a lookbehind on letters stands in for it.
const EPISODE = [/\bS(\d{1,2})\s*[ .-]?\s*E(\d{1,3})\b/i, /\b(\d{1,2})x(\d{1,3})\b/,
  /\b(?:saison|season)\s*(\d{1,2})\D{0,6}?[ée]pisode\s*(\d{1,3})\b/iu, /\b()E(\d{1,3})\b/i,
  /(?<![\p{L}\d])()(?:[ée]pisode|ep\.?)\s*(\d{1,3})\b/iu];
const BARE_WORD = EPISODE.length - 1;
const seriesKey = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\((?:19|20)\d{2}\)/g, "")
  .replace(/[^a-z0-9]/gi, "").toLowerCase();
const pad = (x) => String(x).padStart(2, "0");
function destination(name, seriesDirs) {
  const n = name.trim();
  let m = null, k = 0;
  for (; k < EPISODE.length; k++) if ((m = n.match(EPISODE[k]))) break;
  if (!m) return ["Films", n];
  const season = +(m[1] || n.match(/\b(?:saison|season)\s*(\d{1,2})/i)?.[1] || 1), episode = +m[2];
  const year = n.match(/\(((?:19|20)\d{2})\)/)?.[1];
  const ver = n.match(/\((VF \+ VO|VOSTFR|VF|VO)\)/)?.[1];
  const show = n.slice(0, m.index).replace(/\((?:19|20)\d{2}\)/g, "").replace(/\b(saison|season)\s*\d+\s*$/i, "")
    .replace(/[\s\-–—:|·,]+$/, "").trim() || n;
  // Reuse the existing folder of the show so every episode lands in the same Jellyfin series
  const known = seriesDirs.find((d) => seriesKey(d) === seriesKey(show));
  if (k === BARE_WORD && !known && !/\b(?:saison|season)\s*\d/i.test(n)) return ["Films", n];
  const folder = known || (year ? `${show} (${year})` : show);
  return ["Séries", folder, `Season ${pad(season)}`, `${show} S${pad(season)}E${pad(episode)}${ver ? ` (${ver})` : ""}`];
}
const seriesDirs = native({ action: "series" }).then((r) => r?.series || []);

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const site = hostOf(tab.url);
  document.getElementById("site").textContent = site || "Page système";

  // Blocker: opening the popup arms it for this tab
  const setArmed = async (on) => {
    const { armedTabs = [] } = await chrome.storage.session.get("armedTabs");
    const next = on ? [...new Set([...armedTabs, tab.id])] : armedTabs.filter((id) => id !== tab.id);
    await chrome.storage.session.set({ armedTabs: next });
    toggle.checked = on;
    document.getElementById("state").textContent = on ? "Actif sur cet onglet" : "Désactivé";
  };
  const { blockedCount = 0 } = await chrome.storage.local.get("blockedCount");
  const toggle = document.getElementById("blocker");
  document.getElementById("blocked").textContent =
    `${blockedCount} onglet${blockedCount > 1 ? "s" : ""} bloqué${blockedCount > 1 ? "s" : ""} au total`;
  toggle.onchange = () => setArmed(toggle.checked);
  if (site) await setArmed(true);
  else toggle.disabled = true;

  // Streams
  const k = `tab-${tab.id}`, rk = `real-${tab.id}`, sk = `seen-${tab.id}`;
  const store = await chrome.storage.session.get([k, rk, sk]);
  let list = store[k] || [];
  const realHosts = store[rk] || [];
  // "Nouveau" = caught since the popup was last opened on this tab
  const lastSeen = store[sk];
  chrome.storage.session.set({ [sk]: Date.now() });
  chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: "#0a84ff" });
  const root = document.getElementById("list");

  // Service worker detected: it fetches from the real server while the page sees an obfuscated URL.
  if (realHosts.length) {
    const info = el("div", "card sw");
    info.innerHTML = "<b>Service Worker détecté</b>Les liens pointent vers le vrai serveur de la vidéo.";
    root.before(info);
    // No playlist caught from the worker itself: swap the real host into the page's URLs.
    if (!list.some((e) => e.sw)) {
      const fixed = list.filter((e) => !realHosts.includes(new URL(e.url).host)).map((e) => {
        const u = new URL(e.url);
        u.host = realHosts[0];
        return { ...e, url: u.href, fixed: true };
      });
      list = [...fixed, ...list];
    }
  }

  if (!list.length) {
    root.innerHTML = '<div class="card empty"><b>Aucune vidéo détectée</b>Lance la vidéo puis rouvre ce menu.</div>';
    return;
  }
  // Number streams in detection order so "Flux 3" stays the same between openings.
  [...list].sort((a, b) => a.time - b.time).forEach((e, n) => (e.n = n + 1));
  list.forEach((e) => (e.isNew = lastSeen != null && e.time > lastSeen));

  // Every stream is analysed (the background starts as soon as it is caught) to rank them by real quality.
  const progress = el("div", "card empty", `Analyse de ${list.length} flux…`);
  root.append(progress);
  let done = 0;
  const ask = (e) => Promise.race([
    chrome.runtime.sendMessage({ type: "analyse", url: e.url, page: e.page }),
    new Promise((r) => setTimeout(() => r({ error: "Analyse trop longue" }), 90000)),
  ]).then((info) => { e.info = info || { error: "Analyse impossible" }; progress.textContent = `Analyse des flux… ${++done}/${list.length}`; });
  await Promise.all(list.map(ask));
  progress.remove();

  // Best measured quality first; then real-server URLs, the master playlist, the first loaded.
  const best = (e) => (e.info.error ? null : e.info.formats[0] || {});
  const score = (e) => { const f = best(e); return f ? [1, f.height || 0, f.kbps || 0] : [0, 0, 0]; };
  const real = (e) => (e.sw || e.fixed ? 1 : 0);
  list.sort((a, b) => {
    const sa = score(a), sb = score(b);
    return (sb[0] - sa[0]) || (sb[1] - sa[1]) || (sb[2] - sa[2]) || (real(b) - real(a)) ||
      (isMaster(b.url) - isMaster(a.url)) || (a.time - b.time);
  });

  // Server names are long and meaningless: cards show duration and quality count instead.
  const summary = (info) => [info.duration && hms(info.duration),
    `${info.formats.length || 1} qualité${info.formats.length > 1 ? "s" : ""}`].filter(Boolean).join(" · ");
  const hint = `${tab.title} ${tab.url}`;
  const tpl = document.getElementById("item");

  const card = (e, i) => {
    const node = tpl.content.cloneNode(true).firstElementChild;
    node.querySelector(".name").textContent = isMaster(e.url) ? `Playlist principale (flux ${e.n})` : `Flux vidéo ${e.n}`;
    const tags = node.querySelector(".tags");
    const top = best(e);
    if (top?.height) {
      const q = el("span", "badge q", `${top.height}p`);
      if (top.measured) q.title = "Résolution mesurée sur un segment de la vidéo";
      tags.append(q);
    }
    if (i === 0 && list.length > 1 && top) tags.append(el("span", "badge", "Meilleure qualité"));
    if (e.isNew) { tags.append(el("span", "badge new", "Nouveau")); node.classList.add("new"); }
    if (e.sw) tags.append(el("span", "badge", "Vrai serveur"));
    if (e.fixed) tags.append(el("span", "badge", "Désobfusqué"));
    const meta = node.querySelector(".meta");
    meta.textContent = e.info.error ? "Analyse impossible" : summary(e.info);
    node.querySelector(".copy").onclick = async (ev) => {
      await navigator.clipboard.writeText(e.url);
      await setArmed(false);
      ev.target.textContent = "Copié ✓";
      setTimeout(() => (ev.target.textContent = "Copier le lien"), 1200);
    };
    const box = node.querySelector(".details");
    const more = node.querySelector(".more");
    more.onclick = () => analyse(e, box, meta, more);
    if (i === 0) analyse(e, box, meta, more);
    return node;
  };

  function analyse(e, box, meta, more) {
    more.remove();
    const info = e.info;
    if (info.error) return box.replaceChildren(el("div", "msg err", info.error));

    const ver = version(info, hint);
    if (ver) meta.parentNode.querySelector(".tags").append(el("span", "badge ver", ver));
    meta.textContent = summary(info);
    box.replaceChildren();

    // One row of single-choice chips; returns nothing, calls pick() with the chosen value.
    const chips = (label, items, selected, pick) => {
      const row = el("div", "field");
      row.append(el("div", "flabel", label));
      const wrap = el("div", "chips");
      items.forEach((it) => {
        const c = el("button", "chip" + (it.value === selected ? " on" : ""));
        c.append(it.text);
        if (it.sub) c.append(el("small", null, it.sub));
        c.onclick = () => { wrap.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === c)); pick(it.value); };
        wrap.append(c);
      });
      row.append(wrap);
      box.append(row);
    };

    // Quality
    const formats = info.formats.length ? info.formats : [{ id: "", height: null, kbps: 0 }];
    let fmt = formats[0];
    chips("Qualité", formats.map((f) => ({ value: f, text: f.height ? `${f.height}p` : "Auto",
      sub: [f.size && `≈ ${gb(f.size)}`, f.vcodec && f.vcodec !== "avc1" && f.vcodec.toUpperCase(), f.measured && "mesuré"].filter(Boolean).join(" · ") || (f.kbps ? `${f.kbps} kbps` : "") })),
      fmt, (f) => { fmt = f; label(); });
    if (formats.length === 1) box.append(el("div", "note", "Le site ne propose qu'une seule qualité pour ce flux."));

    // Audio: selectable when the master has several language renditions
    const audios = info.audios;
    let audio = (audios.find((a) => isFr(a.lang) || /fran[cç]/i.test(a.name)) || audios[0])?.id;
    // Keep the track name only when it adds something (e.g. "Audiodescription"), not "English" next to "Anglais"
    const audioText = (a) => {
      if (!a.lang) return a.name;
      const n = langName(a.lang), name = (a.name || "").toLowerCase();
      const same = [n, a.lang, a.id, new Intl.DisplayNames(["en"], { type: "language" }).of(a.lang),
        new Intl.DisplayNames([a.lang], { type: "language" }).of(a.lang)].some((x) => x && name.includes(x.toLowerCase()));
      return !name || same ? n : `${n} (${a.name})`;
    };
    if (audios.length) {
      chips(audios.length > 1 ? "Piste audio" : "Audio", audios.map((a) => ({ value: a.id, text: audioText(a),
        sub: a.channels ? (a.channels >= 6 ? "5.1" : a.channels === 2 ? "Stéréo" : `${a.channels} canaux`) : "" })),
        audio, (v) => { audio = v; });
    } else {
      const lang = info.formats.find((f) => f.lang)?.lang;
      box.append(field("Audio", lang ? `${langName(lang)} · intégré à la vidéo` : "Intégré à la vidéo (langue non indiquée)"));
    }

    // Subtitles: French preselected when the audio is not French
    const subs = info.subtitles;
    let sub = null;
    if (subs.length) {
      if (!audios.some((a) => a.id === audio && isFr(a.lang)) && ver !== "VF") sub = subs.find((s) => isFr(s.lang))?.lang ?? null;
      chips("Sous-titres", [{ value: null, text: "Aucun" }, ...subs.map((s) => ({ value: s.lang, text: langName(s.lang) }))],
        sub, (v) => { sub = v; });
    } else {
      box.append(field("Sous-titres", "Aucun proposé par le flux"));
    }

    // File name
    const nameRow = el("div", "field");
    nameRow.append(el("div", "flabel", "Nom du fichier"));
    const nameWrap = el("label", "filename");
    const input = el("input");
    input.value = cleanTitle(tab.title) + (ver ? ` (${ver})` : "");
    input.spellcheck = false;
    nameWrap.append(input, el("span", null, ".mp4"));
    const dest = el("div", "note");
    nameRow.append(nameWrap, dest);
    box.append(nameRow);
    let dirs = [];
    const where = () => {
      const path = destination(input.value, dirs);
      dest.textContent = path[0] === "Films"
        ? "Rangé dans Films › Films. Pour un épisode, ajoute S01E02 au nom."
        : `Épisode rangé dans Films › ${path.slice(0, -1).join(" › ")}`;
    };
    input.oninput = where;
    where();
    seriesDirs.then((d) => { dirs = d; where(); });

    const go = el("button", "primary go");
    const label = () => (go.textContent = `Télécharger${fmt.height ? ` · ${fmt.height}p` : ""}${fmt.size ? ` · ≈ ${gb(fmt.size)}` : ""}`);
    label();
    const status = el("div", "msg");
    go.onclick = async () => {
      await setArmed(false);
      // A bare "Episode 4" depends on the show folders: don't decide before the host has listed them
      dirs = await seriesDirs;
      const r = await native({ action: "download", url: e.url, format: fmt.id, audio, subs: sub ? [sub] : null,
        referer: e.page, path: destination(input.value, dirs) });
      status.className = r?.error ? "msg err" : "msg";
      status.textContent = r?.error || "Téléchargement lancé dans une fenêtre de terminal ✓";
    };
    box.append(go, status);
  }

  function field(label, text) {
    const row = el("div", "field");
    row.append(el("div", "flabel", label), el("div", "value", text));
    return row;
  }

  root.append(card(list[0], 0));
  if (list.length > 1) {
    const others = el("details", "others");
    const fresh = list.slice(1).filter((e) => e.isNew).length;
    others.append(el("summary", null, `Autres flux (${list.length - 1}${fresh ? ` · ${fresh} nouveau${fresh > 1 ? "x" : ""}` : ""})`));
    list.slice(1).forEach((e, i) => others.append(card(e, i + 1)));
    root.append(others);
  }
})();
