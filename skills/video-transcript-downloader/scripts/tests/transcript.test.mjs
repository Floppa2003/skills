import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const fixtures = fileURLToPath(new URL("./fixtures/", import.meta.url));
const cli = fileURLToPath(new URL("../vtd.js", import.meta.url));
const vtt = "WEBVTT\nLanguage: fr\n\nNOTE ignore this metadata\nnot speech\n\nSTYLE\n::cue { color: lime; }\n\ncue-a\n00:01:05.500 --> 00:01:07.000 align:start\nBonjour <00:01:06.000><b>&amp; bienvenue</b>\n2026\n\ncue-b\n01:01:01.000 --> 01:01:02.000\n[Music]\n";
const srt = "1\r\n00:01:05,500 --> 00:01:07,000\r\nBonjour &amp; bienvenue\r\n2026\r\n\r\n2\r\n01:01:01,000 --> 01:01:02,000\r\n[Music]\r\n";

function run(t, { args = [], direct = "ok", directText = "", format = "vtt", body = vtt, missing = false, wrongLang = "", url = "https://youtu.be/abcdefghijk" } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "vtd-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const bin = path.join(root, "yt-dlp");
  fs.writeFileSync(bin, `#!${process.execPath}\n${fs.readFileSync(path.join(fixtures, "ytdlp.cjs"), "utf8")}`, { mode: 0o700 });
  const argsFile = path.join(root, "args.json");
  const tmp = path.join(root, "tmp");
  fs.mkdirSync(tmp);
  const result = spawnSync(process.execPath, ["--import", path.join(fixtures, "youtube-fetch.mjs"), cli,
    "transcript", "--url", url, ...args, "--", "--ignore-config"], {
    encoding: "utf8", timeout: 10000, maxBuffer: 1024 * 1024,
    env: { ...process.env, PATH: root, TMPDIR: tmp, TMP: tmp, TEMP: tmp,
      VTD_TEST_ARGS: argsFile, VTD_TEST_DIRECT: direct, VTD_TEST_FORMAT: format,
      VTD_TEST_BODY: body, VTD_TEST_SUBS: missing ? "missing" : "present", VTD_TEST_WRONG_LANG: wrongLang,
      VTD_TEST_DIRECT_TEXT: directText },
  });
  assert.ifError(result.error);
  assert.deepEqual(fs.readdirSync(tmp), [], "temporary subtitle directory must be cleaned on success and failure");
  return { ...result, ytArgs: fs.existsSync(argsFile) ? JSON.parse(fs.readFileSync(argsFile, "utf8")) : null };
}

test("direct transcript selects the requested language instead of the first track", (t) => {
  const result = run(t, { args: ["--lang", "fr"] });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "Bonjour & bienvenue\n");
  assert.equal(result.ytArgs, null);
});

test("direct timestamps use seconds, retain hour offsets, and honor cue cleaning", (t) => {
  const result = run(t, { args: ["--lang", "fr", "--timestamps", "--keep-brackets"] });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "[1:05] Bonjour & bienvenue\n[1:01:01] [Music]\n");
});

test("direct default output stays English and strips bracketed cues", (t) => {
  assert.equal(run(t).stdout, "Hello & welcome\n");
  assert.equal(run(t, { args: ["--timestamps"] }).stdout, "[1:05] Hello & welcome\n");
});

for (const [format, body] of [["vtt", vtt], ["srt", srt]]) {
  test(`${format} fallback preserves cue times, multiline/numeric speech, and forwarded isolation`, (t) => {
    const result = run(t, { direct: "fail", format, body, args: ["--lang", "fr", "--timestamps", "--keep-brackets"] });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, "[1:05] Bonjour & bienvenue 2026\n[1:01:01] [Music]\n");
    assert.equal(result.ytArgs[result.ytArgs.indexOf("--sub-lang") + 1], "fr");
    assert.equal(result.ytArgs[result.ytArgs.indexOf("--sub-format") + 1], "vtt/srt");
    assert.ok(result.ytArgs.includes("--ignore-config"));
  });
  test(`${format} fallback without timestamps remains a clean paragraph`, (t) => {
    const result = run(t, { direct: "fail", format, body });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, "Bonjour & bienvenue 2026\n");
  });
}

test("non-YouTube VTT supports minute-only cue times and repeated timed speech", (t) => {
  const result = run(t, { url: "https://video.invalid/example", args: ["--timestamps"],
    body: "WEBVTT\n\n01:05.500 --> 01:07.000\nAgain\n\n01:08.000 --> 01:09.000\nAgain\n" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "[1:05] Again\n[1:08] Again\n");
});

test("unavailable requested language cannot silently return a different track", (t) => {
  const result = run(t, { args: ["--lang", "de"], missing: true });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /no subtitles found.*lang=de/);
});

test("fallback cannot accept a subtitle file in a different language", (t) => {
  const result = run(t, { direct: "fail", args: ["--lang", "fr"], wrongLang: "en" });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /language|lang=fr/);
});

test("transcript requires one language code, not a multi-language selector", (t) => {
  const result = run(t, { args: ["--lang", "fr,en"] });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /language|--lang/);
  assert.equal(result.ytArgs, null);
});

for (const [format, body] of [["vtt", "WEBVTT\n\n"], ["srt", "1\ninvalid --> 00:00:02,000\nHello\n"], ["ass", "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Hello"]]) {
  test(`invalid or unsupported ${format} transcript fails without an untimed success`, (t) => {
    const result = run(t, { direct: "fail", format, body, args: ["--timestamps"] });
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /empty|invalid|unsupported/i);
  });
}

for (const timestamps of [false, true]) {
  test(`direct text preserves escaped angle brackets (timestamps=${timestamps})`, (t) => {
    const result = run(t, { args: timestamps ? ["--timestamps"] : [],
      directText: "When x &lt; 5 and y &gt; 2, type &lt;b&gt;." });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, `${timestamps ? "[1:05] " : ""}When x < 5 and y > 2, type <b>.\n`);
  });
  for (const format of ["vtt", "srt"]) {
    test(`${format} preserves literal text while stripping real markup (timestamps=${timestamps})`, (t) => {
      const header = format === "vtt" ? "WEBVTT\n\n" : "1\n";
      const result = run(t, { direct: "fail", format, args: timestamps ? ["--timestamps"] : [],
        body: `${header}00:01:05.500 --> 00:01:07.000\n<b>When x &lt; 5 and y &gt; 2, type &lt;b&gt;.</b>\n` });
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stdout, `${timestamps ? "[1:05] " : ""}When x < 5 and y > 2, type <b>.\n`);
    });
  }
}

for (const format of ["vtt", "srt"]) {
  test(`${format} paragraph deduplicates overlapping lines without losing cue times`, (t) => {
    const header = format === "vtt" ? "WEBVTT\n\n" : "";
    const body = `${header}1\n00:01:05.500 --> 00:01:07.000\nHello\nworld\n\n2\n00:01:08.000 --> 00:01:10.000\nworld\nagain\n`;
    const paragraph = run(t, { direct: "fail", format, body });
    assert.equal(paragraph.status, 0, paragraph.stderr);
    assert.equal(paragraph.stdout, "Hello world again\n");
    const timed = run(t, { direct: "fail", format, body, args: ["--timestamps"] });
    assert.equal(timed.status, 0, timed.stderr);
    assert.equal(timed.stdout, "[1:05] Hello world\n[1:08] world again\n");
  });
}

for (const [directText, expected] of [["very\nvery important", "very very important"], ["we\nknow we can", "we know we can"]]) {
  test(`direct multiline speech preserves deliberate repetition: ${expected}`, (t) => {
    const paragraph = run(t, { directText });
    assert.equal(paragraph.status, 0, paragraph.stderr);
    assert.equal(paragraph.stdout, expected + "\n");
    const timed = run(t, { directText, args: ["--timestamps"] });
    assert.equal(timed.status, 0, timed.stderr);
    assert.equal(timed.stdout, `[1:05] ${expected}\n`);
  });
}
