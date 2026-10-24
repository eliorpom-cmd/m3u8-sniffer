// Tests for the popup's pure helpers (naming, Jellyfin destination, VF/VO), loaded from extension/popup.js
// without Chrome: only the part before the first call to the native host is evaluated.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../extension/popup.js", import.meta.url), "utf8");
const helpers = source.slice(0, source.indexOf("const seriesDirs = native("));
assert.ok(helpers.includes("function destination"), "popup.js changed shape: update this test's loader");
const { destination, version, cleanTitle, hostOf, isMaster, gb, hms } =
  vm.runInNewContext(`${helpers};({ destination, version, cleanTitle, hostOf, isMaster, gb, hms })`, { Intl, URL });

test("a film goes to Films/ under its own name", () => {
  assert.deepEqual([...destination("Dune (2021) (VF)", [])], ["Films", "Dune (2021) (VF)"]);
});

test("S01E02 goes to the series folder, season and episode padded", () => {
  assert.deepEqual([...destination("The Office (2005) S02E07 (VO)", [])],
    ["Séries", "The Office (2005)", "Season 02", "The Office S02E07 (VO)"]);
});

test("1x02 and Saison 1 Épisode 2 are episodes too", () => {
  assert.deepEqual([...destination("Lupin 1x02", [])].slice(1), ["Lupin", "Season 01", "Lupin S01E02"]);
  assert.deepEqual([...destination("Lupin Saison 2 Épisode 5", [])].slice(1), ["Lupin", "Season 02", "Lupin S02E05"]);
});

test("a bare \"Episode 4\" is a film, unless the show has its folder or the name says Saison", () => {
  assert.deepEqual([...destination("Star Wars Episode 4 (VO)", [])], ["Films", "Star Wars Episode 4 (VO)"]);
  assert.equal(destination("Arcane Episode 4", ["Arcane (2021)"])[1], "Arcane (2021)");
  assert.equal(destination("Arcane Saison 2 Episode 4", [])[2], "Season 02");
  assert.equal(destination("Arcane Épisode 4", ["Arcane (2021)"])[1], "Arcane (2021)");
  assert.equal(destination("arcane épisode 4", ["Arcane (2021)"])[1], "Arcane (2021)");
  assert.deepEqual([...destination("Star Wars Ep 4 (VO)", [])], ["Films", "Star Wars Ep 4 (VO)"]);
  assert.equal(destination("The Office Season 2 Episode 4", [])[2], "Season 02");
});

test("a bare E03 is season 1, unless the name says otherwise", () => {
  assert.equal(destination("Arcane E03", [])[2], "Season 01");
  assert.equal(destination("Arcane Saison 2 E03", [])[2], "Season 02");
});

test("an existing show folder is reused whatever the accents, case and year", () => {
  const dirs = ["Les Revenants (2012)", "Dark"];
  assert.equal(destination("les revenants S01E01", dirs)[1], "Les Revenants (2012)");
  assert.equal(destination("Dark (2017) S03E08", dirs)[1], "Dark");
});

test("a screen resolution is not an episode number", () => {
  assert.equal(destination("Concert 1920x1080", [])[0], "Films");
});

test("version from audio and subtitle languages, then from the page title", () => {
  const info = (audios, subs = []) => ({ audios: audios.map((lang) => ({ lang })), formats: [], subtitles: subs.map((lang) => ({ lang })) });
  assert.equal(version(info(["fr", "en"]), ""), "VF + VO");
  assert.equal(version(info(["fra"]), ""), "VF");
  assert.equal(version(info(["en"], ["fr"]), ""), "VOSTFR");
  assert.equal(version(info(["en"]), ""), "VO");
  assert.equal(version(info([]), "Film en VOSTFR"), "VOSTFR");
  assert.equal(version(info([]), "Film truefrench"), "VF");
  assert.equal(version(info([]), "Film"), null);
});

test("page titles are cleaned into file names", () => {
  assert.equal(cleanTitle("Regarder Dune en streaming VF - MonSite"), "Dune");
  assert.equal(cleanTitle("Mission: Impossible | Site"), "Mission - Impossible");
  assert.equal(cleanTitle('A/B*C?"D'), "ABCD");
  assert.equal(cleanTitle(""), "vidéo");
  assert.ok(cleanTitle("x".repeat(200)).length <= 80);
});

test("small helpers", () => {
  assert.equal(hostOf("https://www.example.com/a"), "example.com");
  assert.equal(hostOf("not a url"), "");
  assert.ok(isMaster("https://cdn/x/master.m3u8?token=1"));
  assert.ok(!isMaster("https://cdn/x/720p.m3u8"));
  assert.equal(gb(1.5e9), "1,5 Go");
  assert.equal(gb(250e6), "250 Mo");
  assert.equal(hms(3 * 3600 + 5 * 60), "3 h 05");
  assert.equal(hms(42 * 60), "42 min");
});
