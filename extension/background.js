// Collect .m3u8 URLs per tab (including those fetched by a page's service worker), and close ad tabs opened by pages where the blocker is on.
const key = (tabId) => `tab-${tabId}`;
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };

const PLAYLIST = /\.m3u8(\?|$)/i;
const SEGMENT = /\.(ts|m4s)(\?|$)/i;
const originOf = (u) => { try { return new URL(u).origin; } catch { return ""; } };

// Service workers fetch with tabId -1: remember which tab owns each page/iframe origin to attribute them.
// Frame origins are persisted (the extension worker can be killed), initiators only kept in memory.
const owners = new Map();
async function ownerTab(origin) {
  if (!origin) return null;
  if (owners.has(origin)) return owners.get(origin);
  const { frameOrigins = {} } = await chrome.storage.session.get("frameOrigins");
  if (frameOrigins[origin] != null) return frameOrigins[origin];
  const tabs = await chrome.tabs.query({});
  return tabs.find((t) => originOf(t.url || "") === origin)?.id ?? null;
}

// Analyse each stream as soon as it is caught, so the popup can rank them by real quality right away.
const HOST = "dev.byelior.m3u8";
const pending = new Map();
function analyse(url, page) {
  if (pending.has(url)) return pending.get(url);
  const ck = `info:${url}`;
  const job = chrome.storage.session.get(ck).then(async (cached) => {
    if (cached[ck]) return cached[ck];
    const info = await new Promise((resolve) => chrome.runtime.sendNativeMessage(HOST, { action: "formats", url, referer: page },
      (res) => resolve(chrome.runtime.lastError ? { error: "Hôte non installé : lance install-host.sh" } : res)));
    if (info && !info.error) await chrome.storage.session.set({ [ck]: info });
    return info || { error: "Pas de réponse de l'hôte" };
  }).finally(() => pending.delete(url));
  pending.set(url, job);
  return job;
}
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type !== "analyse") return;
  analyse(msg.url, msg.page).then(reply);
  return true;
});

async function addStream(tabId, url, sw) {
  const k = key(tabId);
  const list = (await chrome.storage.session.get(k))[k] || [];
  if (list.some((e) => e.url === url)) return;
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab) return;
  list.push({ url, time: Date.now(), page: tab.url || "", sw });
  await chrome.storage.session.set({ [k]: list });
  // Green badge: streams arrived since the popup was last opened on this tab (e.g. another server tried)
  const sk = `seen-${tabId}`;
  const seen = (await chrome.storage.session.get(sk))[sk];
  chrome.action.setBadgeText({ tabId, text: String(list.length) });
  chrome.action.setBadgeBackgroundColor({ tabId, color: seen ? "#30d158" : "#0a84ff" });
  analyse(url, tab.url || "");
}

// Real host = domain a service worker actually hits for playlists/segments behind an obfuscated URL.
async function addRealHost(tabId, url) {
  const k = `real-${tabId}`;
  const hosts = (await chrome.storage.session.get(k))[k] || [];
  const h = new URL(url).host;
  if (!hosts.includes(h)) await chrome.storage.session.set({ [k]: [...hosts, h] });
}

async function onMedia(details, kind) {
  if (details.tabId >= 0) return kind === "playlist" && addStream(details.tabId, details.url, false);
  const tabId = await ownerTab(details.initiator);
  if (tabId == null) return;
  await addRealHost(tabId, details.url);
  if (kind === "playlist") await addStream(tabId, details.url, true);
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId >= 0) {
      if (details.initiator) owners.set(details.initiator, details.tabId);
      if (details.type === "main_frame" || details.type === "sub_frame") {
        const origin = originOf(details.url);
        owners.set(origin, details.tabId);
        chrome.storage.session.get("frameOrigins").then(({ frameOrigins = {} }) =>
          chrome.storage.session.set({ frameOrigins: { ...frameOrigins, [origin]: details.tabId } }));
      }
    }
    if (PLAYLIST.test(details.url)) onMedia(details, "playlist");
    else if (SEGMENT.test(details.url)) onMedia(details, "segment");
  },
  { urls: ["<all_urls>"] }
);

// Disguised files (playlist served as .png, .txt…): recognise them by their content type.
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (PLAYLIST.test(details.url) || SEGMENT.test(details.url)) return;
    const type = details.responseHeaders?.find((h) => h.name.toLowerCase() === "content-type")?.value || "";
    if (/mpegurl/i.test(type)) onMedia(details, "playlist");
    else if (/mp2t/i.test(type)) onMedia(details, "segment");
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// Reset the list when the tab navigates to a new page or closes.
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === "loading" && info.url) {
    chrome.storage.session.remove([key(tabId), `real-${tabId}`, `seen-${tabId}`]);
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove([key(tabId), `real-${tabId}`, `seen-${tabId}`]));

// Popup blocker: off by default, armed per tab when the popup opens, disarmed after copy/download/toggle.
async function isArmed(tabId) {
  const { armedTabs = [] } = await chrome.storage.session.get("armedTabs");
  return armedTabs.includes(tabId);
}

chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.openerTabId == null || !(await isArmed(tab.openerTabId))) return;
  const opener = await chrome.tabs.get(tab.openerTabId).catch(() => null);
  if (!opener) return;
  // Browser pages (new tab, settings) and same-site links stay allowed.
  const target = tab.pendingUrl || tab.url || "";
  if (/^(chrome|edge|about|chrome-extension):/.test(target) && target !== "about:blank") return;
  if (target && hostOf(target) === hostOf(opener.url || "")) return;
  await chrome.tabs.remove(tab.id).catch(() => {});
  chrome.tabs.update(opener.id, { active: true });
  const { blockedCount = 0 } = await chrome.storage.local.get("blockedCount");
  chrome.storage.local.set({ blockedCount: blockedCount + 1 });
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const { armedTabs = [] } = await chrome.storage.session.get("armedTabs");
  chrome.storage.session.set({ armedTabs: armedTabs.filter((id) => id !== tabId) });
});

// Unpacked install only: reload the extension by itself when one of its files changes on disk.
const WATCHED = ["manifest.json", "background.js", "popup.html", "popup.js", "popup.css"];
async function filesHash() {
  const texts = await Promise.all(WATCHED.map((f) => fetch(chrome.runtime.getURL(f), { cache: "no-store" }).then((r) => r.text())));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texts.join("\0")));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function startWatching() {
  if ((await chrome.management.getSelf()).installType !== "development") return;
  await chrome.storage.local.set({ devHash: await filesHash() });
  chrome.alarms.create("dev-reload", { periodInMinutes: 0.05 });
}
chrome.runtime.onInstalled.addListener(startWatching);
chrome.runtime.onStartup.addListener(startWatching);
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "dev-reload") return;
  const { devHash } = await chrome.storage.local.get("devHash");
  if (devHash && devHash !== (await filesHash())) chrome.runtime.reload();
});
