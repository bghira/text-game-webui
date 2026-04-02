/**
 * Chatterbox TTS Web Worker
 * Runs Chatterbox Turbo via WebGPU using transformers.js v4.
 *
 * Message protocol (same shape as kokoro-worker):
 *   IN:  { text, referenceAudioUrl?, exaggeration? }
 *   OUT: { status: "device"|"loading"|"ready"|"complete"|"error", ... }
 */
import {
  AutoModel,
  AutoProcessor,
  env,
} from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4";

env.allowLocalModels = false;

const MODEL_ID = "spacekaren/chatterbox-turbo-webgpu";
const SAMPLE_RATE = 24000;

let model = null;
let processor = null;
let loadPromise = null;

/* ---- Reference-audio cache (keyed by URL) ---- */
const refCache = new Map();

/* ==== WAV helpers ==== */

function _writeStr(view, off, s) {
  for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
}

function encodeWav(samples) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  _writeStr(v, 0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  _writeStr(v, 8, "WAVE");
  _writeStr(v, 12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);         // PCM
  v.setUint16(22, 1, true);         // mono
  v.setUint32(24, SAMPLE_RATE, true);
  v.setUint32(28, SAMPLE_RATE * 2, true);
  v.setUint16(32, 2, true);         // block align
  v.setUint16(34, 16, true);        // bits per sample
  _writeStr(v, 36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/** Minimal WAV decoder (PCM-16 or PCM-float32, first channel only). */
function decodeWav(buffer) {
  const v = new DataView(buffer);
  const channels = v.getUint16(22, true);
  const sr = v.getUint32(24, true);
  const bps = v.getUint16(34, true);
  /* locate the 'data' chunk */
  let off = 12;
  while (off < buffer.byteLength - 8) {
    const id = String.fromCharCode(
      v.getUint8(off), v.getUint8(off + 1),
      v.getUint8(off + 2), v.getUint8(off + 3),
    );
    const sz = v.getUint32(off + 4, true);
    if (id === "data") { off += 8; break; }
    off += 8 + sz;
  }
  const bytesPerFrame = (bps / 8) * channels;
  const n = Math.floor((buffer.byteLength - off) / bytesPerFrame);
  const out = new Float32Array(n);
  if (bps === 16) {
    for (let i = 0; i < n; i++) out[i] = v.getInt16(off + i * channels * 2, true) / 32768;
  } else if (bps === 32) {
    for (let i = 0; i < n; i++) out[i] = v.getFloat32(off + i * channels * 4, true);
  }
  /* Resample to 24 kHz if the source differs */
  if (sr !== SAMPLE_RATE && sr > 0) {
    const ratio = sr / SAMPLE_RATE;
    const newLen = Math.round(n / ratio);
    const res = new Float32Array(newLen);
    for (let i = 0; i < newLen; i++) {
      const si = i * ratio;
      const lo = Math.floor(si);
      const hi = Math.min(lo + 1, n - 1);
      const f = si - lo;
      res[i] = out[lo] * (1 - f) + out[hi] * f;
    }
    return res;
  }
  return out;
}

async function fetchRefAudio(url) {
  if (!url) return null;
  if (refCache.has(url)) return refCache.get(url);
  try {
    const resp = await fetch(url);
    const buf = await resp.arrayBuffer();
    const data = decodeWav(buf);
    refCache.set(url, data);
    return data;
  } catch (err) {
    console.warn("[Chatterbox] ref-audio fetch failed:", err);
    return null;
  }
}

/* ==== Model lifecycle ==== */

async function ensureModel() {
  if (model && processor) return true;
  if (loadPromise) { await loadPromise; return !!(model && processor); }

  loadPromise = (async () => {
    let device = "webgpu";
    try {
      self.postMessage({ status: "device", device: "webgpu" });
      model = await AutoModel.from_pretrained(MODEL_ID, {
        device: "webgpu",
        dtype: "q4f16",
        progress_callback: (p) => {
          if (p.status === "progress" && p.progress != null) {
            self.postMessage({
              status: "loading",
              progress: Math.round(p.progress),
              message: "Loading Chatterbox (" + Math.round(p.progress) + "%)…",
            });
          }
        },
      });
      processor = await AutoProcessor.from_pretrained(MODEL_ID);
    } catch (err) {
      console.warn("[Chatterbox] WebGPU failed, trying WASM:", err);
      device = "wasm";
      try {
        self.postMessage({ status: "device", device: "wasm" });
        model = await AutoModel.from_pretrained(MODEL_ID, { device: "wasm", dtype: "q4" });
        processor = await AutoProcessor.from_pretrained(MODEL_ID);
      } catch (err2) {
        self.postMessage({ status: "error", message: "Failed to load Chatterbox: " + err2.message });
        return;
      }
    }
    self.postMessage({ status: "ready", device, voices: {} });
  })();

  await loadPromise;
  return !!(model && processor);
}

/* ==== Start loading immediately when worker is created ==== */
ensureModel();

/* ==== Generation ==== */

self.onmessage = async (e) => {
  const ok = await ensureModel();
  if (!ok) return;

  try {
    let { text, referenceAudioUrl, exaggeration } = e.data;
    if (exaggeration == null) exaggeration = 0.5;

    /* Convert <emotive> → [emotive] for Chatterbox tokenizer */
    text = (text || "").replace(/<(\w+)>/g, "[$1]");

    const refAudio = await fetchRefAudio(referenceAudioUrl);
    const inputs = await processor(text, refAudio);

    const waveform = await model.generate({
      ...inputs,
      exaggeration,
      max_new_tokens: 2048,
    });

    const raw = waveform.data || waveform;
    const samples = raw instanceof Float32Array ? raw : new Float32Array(raw);
    const blob = encodeWav(samples);
    const url = URL.createObjectURL(blob);

    self.postMessage({ status: "complete", audio: url });
  } catch (err) {
    self.postMessage({ status: "error", message: err.message || String(err) });
  }
};
