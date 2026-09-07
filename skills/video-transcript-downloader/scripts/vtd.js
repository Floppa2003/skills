#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { YoutubeTranscript } from "youtube-transcript-plus";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function die(message, code = 1) {
  process.stderr.write(String(message).trimEnd() + "\n");
  process.exit(code);
}

function parseArgs(argv) {
  // Tiny no-deps parser.
  // - `--flag` => boolean
  // - `--key value`
  // - `--` => forward remaining args to yt-dlp
  const positional = [];
  const opts = {};
  let i = 0;
  while (i < argv.length) {
    const a = argv[i];
    if (a === "--") {
      opts.extra = argv.slice(i + 1);
      break;
    }
    if (!a.startsWith("--")) {
      positional.push(a);
      i += 1;
      continue;
    }
    const key = a.slice(2);
    const next = argv[i + 1];
    const isValue = next !== undefined && !next.startsWith("--");
    if (!isValue) {
      opts[key] = true;
      i += 1;
      continue;
    }
    if (opts[key] === undefined) opts[key] = next;
    else if (Array.isArray(opts[key])) opts[key].push(next);
    else opts[key] = [opts[key], next];
    i += 2;
  }
  return { positional, opts };
}

function toArray(v) {
  if (v === undefined) return [];
  if (Array.isArray(v)) return v;
  return [v];
}

function which(cmd) {
  // Avoid shelling out to `which`; keep it portable + fast.
  const envPath = process.env.PATH || "";
  const parts = envPath.split(path.delimiter);
  for (const p of parts) {
    const full = path.join(p, cmd);
    if (fs.existsSync(full)) return full;
  }
  return null;
}

function resolveBin(name, fallback) {
  return which(name) || (fallback && fs.existsSync(fallback) ? fallback : null);
}

function run(cmd, args, { cwd } = {}) {
  return new Promise((resolve) => {
    // Capture stdout + stderr to keep yt-dlp’s error context intact.
    const child = spawn(cmd, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (out += d.toString()));
    child.on("close", (code) => resolve({ code, out }));
  });
}

function isYouTubeUrl(url) {
  return /(^https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i.test(url);
}

function extractYouTubeId(input) {
  if (!input) return null;
  const raw = String(input).trim();
  if (/^[a-zA-Z0-9_-]{11}$/.test(raw)) return raw;
  const m = raw.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : null;
}

function decodeHtmlEntities(input) {
  if (!input) return input;
  // Some transcripts come back double-encoded (e.g. "&amp;#39;").
  // Decode up to 2 passes; stop once stable.
  let text = input;
  for (let i = 0; i < 2; i++) {
    const decoded = text
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'")
      .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(Number(dec)))
      .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)));
    if (decoded === text) break;
    text = decoded;
  }
  return text;
}

function formatTimestamp(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function cleanSegments(segments, { keepBrackets, subtitleMarkup } = {}) {
  const cleaned = [];
  let prev = "";

  for (const seg of segments) {
    const s = String(seg || "")
      .replace(/\s+/g, " ")
      .trim();
    if (!s) continue;

    // Strip actual subtitle markup before decoding escaped literal speech.
    // The direct transcript library already returns text, not subtitle markup.
    const withoutTags = subtitleMarkup ? s.replace(/<[^>]+>/g, "").trim() : s;
    const decoded = decodeHtmlEntities(withoutTags);
    const withoutBrackets = keepBrackets ? decoded : decoded.replace(/\[[^\]]*\]/g, "").trim();
    const withoutCurlies = withoutBrackets.replace(/\{[^}]+\}/g, "").replace(/♪/g, "").trim();
    const t = withoutCurlies.replace(/\s+/g, " ").trim();
    if (!t) continue;
    if (t === prev) continue;
    // Dedup heuristic: captions often repeat previous line with a longer suffix.
    if (prev && t.startsWith(prev)) {
      const newPart = t.slice(prev.length).trim();
      if (newPart) cleaned.push(newPart);
    } else if (prev && t.includes(prev)) {
      // Another common pattern: current line contains previous line in the middle.
      const idx = t.indexOf(prev);
      const newPart = (t.slice(0, idx) + t.slice(idx + prev.length)).trim();
      if (newPart) cleaned.push(newPart);
    } else {
      cleaned.push(t);
    }
    prev = t;
  }

  return cleaned;
}

function toParagraph(segments, { keepBrackets, subtitleMarkup } = {}) {
  const cleaned = cleanSegments(segments, { keepBrackets, subtitleMarkup });
  return cleaned.join(" ").replace(/\s+/g, " ").trim();
}

function parseCueTime(value) {
  const match = value.match(/^(?:(\d{2,}):)?([0-5]\d):([0-5]\d)[.,](\d{3})$/);
  if (!match) throw new Error(`invalid subtitle timestamp: ${value}`);
  return Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4]) / 1000;
}

function parseSubtitles(text) {
  const cues = [];
  for (const block of text.replace(/^\uFEFF/, "").trim().split(/\r?\n\s*\r?\n/)) {
    if (!block || /^(WEBVTT|NOTE|STYLE|REGION)(?:\s|$)/.test(block)) continue;
    const lines = block.split(/\r?\n/).map((line) => line.trim());
    const index = lines.findIndex((line) => line.includes("-->"));
    if (index < 0 || index > 1) throw new Error("invalid subtitle cue: missing timing line");
    const timing = lines[index].match(/^(\S+)\s+-->\s+(\S+)(?:\s.*)?$/);
    if (!timing) throw new Error(`invalid subtitle timing line: ${lines[index]}`);
    const offset = parseCueTime(timing[1]);
    if (parseCueTime(timing[2]) < offset) throw new Error("invalid subtitle cue: end precedes start");
    cues.push({ offset, text: lines.slice(index + 1).join("\n") });
  }
  return cues;
}

function renderTranscript(cues, { timestamps, keepBrackets, subtitleMarkup = false }) {
  const cleaning = { keepBrackets, subtitleMarkup };
  const output = timestamps
    ? cues.map((cue) => {
      if (!Number.isFinite(cue.offset) || cue.offset < 0) throw new Error("invalid transcript offset (expected nonnegative seconds)");
      const text = toParagraph([cue.text], cleaning);
      return text ? `[${formatTimestamp(cue.offset)}] ${text}` : "";
    }).filter(Boolean).join("\n")
    : toParagraph(cues.flatMap((cue) => subtitleMarkup ? cue.text.split(/\r?\n/) : [cue.text]), cleaning);
  if (!output) throw new Error("empty transcript");
  return output + "\n";
}

async function ytDlpSubtitlesToTemp({ url, lang, ytdlpPath, extra, subtitleFormat }) {
  const ytdlp = ytdlpPath || resolveBin("yt-dlp", "/opt/homebrew/bin/yt-dlp");
  if (!ytdlp) die("missing yt-dlp; install `yt-dlp` and ensure it is on PATH");

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "vtd-subs-"));
  const outTemplate = path.join(tmpDir, "%(id)s.%(ext)s");

  const args = [];
  args.push(
    "--write-sub",
    "--write-auto-sub",
    "--skip-download",
    "--sub-lang",
    lang,
    "-o",
    outTemplate,
  );
  if (subtitleFormat) args.push("--sub-format", subtitleFormat);
  if (extra?.length) args.push(...extra);
  args.push(url);

  const r = await run(ytdlp, args);
  if (r.code !== 0) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    die(r.out.trim() || "yt-dlp subtitle download failed");
  }

  const files = fs
    .readdirSync(tmpDir)
    .map((f) => path.join(tmpDir, f))
    .filter((f) => /\.(vtt|srt|ass|ttml)$/i.test(f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);

  if (files.length === 0) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    die(`no subtitles found (lang=${lang})`);
  }

  return { tmpDir, subtitlePath: files[0] };
}

async function cmdTranscript({ url, lang, timestamps, keepBrackets, extra }) {
  if (!url) die("missing --url");
  if (typeof lang !== "string" || !/^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$/.test(lang)) {
    throw new Error("transcript --lang requires one language code, such as en or pt-BR");
  }

  if (isYouTubeUrl(url)) {
    const id = extractYouTubeId(url);
    if (id) {
      try {
        // Preferred path: direct transcript fetch (no yt-dlp / no files).
        const transcript = await YoutubeTranscript.fetchTranscript(id, { lang });
        process.stdout.write(renderTranscript(transcript, { timestamps, keepBrackets }));
        return;
      } catch (error) {
        process.stderr.write(`Direct transcript failed (${error.message}); trying yt-dlp for lang=${lang}.\n`);
      }
    }
  }

  const { tmpDir, subtitlePath } = await ytDlpSubtitlesToTemp({
    url,
    lang,
    extra,
    subtitleFormat: "vtt/srt",
  });

  try {
    const stem = path.basename(subtitlePath, path.extname(subtitlePath));
    if (!stem.endsWith(`.${lang}`)) throw new Error(`subtitle language does not match lang=${lang}`);
    const raw = fs.readFileSync(subtitlePath, "utf8");
    if (!/\.(srt|vtt)$/i.test(subtitlePath)) throw new Error("unsupported transcript subtitle format: expected VTT or SRT");
    process.stdout.write(renderTranscript(parseSubtitles(raw), { timestamps, keepBrackets, subtitleMarkup: true }));
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function cmdSubs({ url, lang, outputDir, extra }) {
  if (!url) die("missing --url");

  const { tmpDir, subtitlePath } = await ytDlpSubtitlesToTemp({
    url,
    lang,
    extra,
  });

  try {
    const out = path.resolve(outputDir);
    fs.mkdirSync(out, { recursive: true });
    const dest = path.join(out, path.basename(subtitlePath));
    fs.copyFileSync(subtitlePath, dest);
    process.stdout.write(dest + "\n");
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function cmdDownload({ url, outputDir, extra }) {
  if (!url) die("missing --url");
  const ytdlp = resolveBin("yt-dlp", "/opt/homebrew/bin/yt-dlp");
  if (!ytdlp) die("missing yt-dlp; install `yt-dlp` and ensure it is on PATH");

  const out = path.resolve(outputDir);
  fs.mkdirSync(out, { recursive: true });

  const args = [];

  // `--print after_move:filepath` gives the final path after merges/remux.
  args.push("-P", out, "-o", "%(title).200B (%(id)s).%(ext)s", "-S", "res,ext:mp4:m4a,tbr", "--print", "after_move:filepath");
  if (extra?.length) args.push(...extra);
  args.push(url);

  const r = await run(ytdlp, args);
  if (r.code !== 0) die(r.out.trim() || "yt-dlp download failed");

  const lines = r.out.split("\n").map((l) => l.trim());
  const filePath = lines.find((l) => l.startsWith("/") && fs.existsSync(l));
  if (!filePath) die(r.out.trim() || "could not determine downloaded file path");
  process.stdout.write(path.resolve(filePath) + "\n");
}

async function cmdAudio({ url, outputDir, extra }) {
  if (!url) die("missing --url");
  const ytdlp = resolveBin("yt-dlp", "/opt/homebrew/bin/yt-dlp");
  if (!ytdlp) die("missing yt-dlp; install `yt-dlp` and ensure it is on PATH");
  const ffmpeg = resolveBin("ffmpeg", "/opt/homebrew/bin/ffmpeg");
  if (!ffmpeg) die("missing ffmpeg; install `ffmpeg` (needed for audio extraction)");

  const out = path.resolve(outputDir);
  fs.mkdirSync(out, { recursive: true });

  const args = [];

  args.push(
    "--ffmpeg-location",
    ffmpeg,
    "-P",
    out,
    "-o",
    "%(title).200B (%(id)s).%(ext)s",
    "-x",
    "--audio-format",
    "mp3",
    "--print",
    "after_move:filepath",
  );
  if (extra?.length) args.push(...extra);
  args.push(url);

  const r = await run(ytdlp, args);
  if (r.code !== 0) die(r.out.trim() || "yt-dlp audio failed");

  const lines = r.out.split("\n").map((l) => l.trim());
  const filePath = lines.find((l) => l.startsWith("/") && fs.existsSync(l));
  if (!filePath) die(r.out.trim() || "could not determine downloaded file path");
  process.stdout.write(path.resolve(filePath) + "\n");
}

async function cmdFormats({ url, extra }) {
  if (!url) die("missing --url");
  const ytdlp = resolveBin("yt-dlp", "/opt/homebrew/bin/yt-dlp");
  if (!ytdlp) die("missing yt-dlp; install `yt-dlp` and ensure it is on PATH");

  // Print raw yt-dlp format table; user picks `--format <id>` for downloads.
  const args = ["-F"];
  if (extra?.length) args.push(...extra);
  args.push(url);

  const r = await run(ytdlp, args);
  if (r.code !== 0) die(r.out.trim() || "yt-dlp formats failed");
  process.stdout.write(r.out);
}

function usage(command) {
  const rel = path.relative(process.cwd(), path.join(__dirname, "vtd.js"));
  const lines = {
    transcript: [
      "usage:",
      `  ${rel} transcript --url 'https://…' [--lang en] [--timestamps] [--keep-brackets] [-- <yt-dlp extra…>]`,
      "",
      "flags:",
      "  --url URL          video URL",
      "  --lang CODE        subtitle language (default: en)",
      "  --timestamps       print cue start times; fail if no usable timed transcript",
      "  --keep-brackets    keep bracketed cues like [Music]",
    ],
    download: [
      "usage:",
      `  ${rel} download --url 'https://…' [--output-dir ~/Downloads] [-- <yt-dlp extra…>]`,
      "",
      "flags:",
      "  --url URL          video URL",
      "  --output-dir DIR   output directory",
    ],
    audio: [
      "usage:",
      `  ${rel} audio --url 'https://…' [--output-dir ~/Downloads] [-- <yt-dlp extra…>]`,
      "",
      "flags:",
      "  --url URL          video URL",
      "  --output-dir DIR   output directory",
    ],
    subs: [
      "usage:",
      `  ${rel} subs --url 'https://…' [--output-dir ~/Downloads] [--lang en] [-- <yt-dlp extra…>]`,
      "",
      "flags:",
      "  --url URL          video URL",
      "  --lang CODE        subtitle language (default: en)",
      "  --output-dir DIR   output directory",
    ],
    formats: [
      "usage:",
      `  ${rel} formats --url 'https://…' [-- <yt-dlp extra…>]`,
      "",
      "flags:",
      "  --url URL          video URL",
    ],
  };
  if (command && lines[command]) return lines[command].join("\n");
  return [
    "usage:",
    `  ${rel} transcript --url 'https://…' [--lang en] [--timestamps] [--keep-brackets] [-- <yt-dlp extra…>]`,
    `  ${rel} download   --url 'https://…' [--output-dir ~/Downloads] [-- <yt-dlp extra…>]`,
    `  ${rel} audio      --url 'https://…' [--output-dir ~/Downloads] [-- <yt-dlp extra…>]`,
    `  ${rel} subs       --url 'https://…' [--output-dir ~/Downloads] [--lang en] [-- <yt-dlp extra…>]`,
    `  ${rel} formats    --url 'https://…' [-- <yt-dlp extra…>]`,
  ].join("\n");
}

async function main() {
  const { positional, opts } = parseArgs(process.argv.slice(2));
  const cmd = positional[0];

  if (!cmd || cmd === "help" || cmd === "-h" || cmd === "--help") {
    process.stdout.write(usage() + "\n");
    return;
  }

  if (opts.help || positional[1] === "help" || positional[1] === "-h" || positional[1] === "--help") {
    process.stdout.write(usage(cmd) + "\n");
    return;
  }

  const url = opts.url;
  const lang = opts.lang || "en";
  const outputDir = opts["output-dir"] || path.join(os.homedir(), "Downloads");

  const timestamps = Boolean(opts.timestamps);
  const keepBrackets = Boolean(opts["keep-brackets"]);
  const extra = opts.extra || [];

  if (cmd === "transcript") {
    await cmdTranscript({ url, lang, timestamps, keepBrackets, extra });
    return;
  }
  if (cmd === "download") {
    await cmdDownload({ url, outputDir, extra });
    return;
  }
  if (cmd === "audio") {
    await cmdAudio({ url, outputDir, extra });
    return;
  }
  if (cmd === "subs") {
    await cmdSubs({ url, lang, outputDir, extra });
    return;
  }
  if (cmd === "formats") {
    await cmdFormats({ url, extra });
    return;
  }

  die(`unknown command: ${cmd}\n\n${usage()}`);
}

main().catch((e) => die(e?.stack || e?.message || String(e)));
