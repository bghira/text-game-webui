/**
 * Chatterbox TTS Web Worker
 * Runs Chatterbox via WebGPU/WASM using transformers.js v4.
 *
 * Message protocol (same shape as kokoro-worker):
 *   IN:  { text, referenceAudioUrl?, exaggeration? }
 *   OUT: { status: "device"|"loading"|"ready"|"complete"|"error", ... }
 *
 * Speaker embeddings are computed once per reference-audio URL and cached.
 */
/*
 * Local copy of transformers.js v4.0.1 web bundle (422 KB).
 * The CDN builds have a stale cache missing ChatterboxModel registration,
 * so we serve the bundle locally from node_modules dist.
 */
import {
  ChatterboxModel,
  AutoProcessor,
  Tensor,
  env,
} from "/static/js/transformers.web.min.js";

env.allowLocalModels = false;

const MODEL_ID = "onnx-community/chatterbox-ONNX";
const SAMPLE_RATE = 24000;

/* Per-session dtype — only language_model has quantized variants */
const DTYPE_CONFIGS = {
  webgpu: {
    embed_tokens: "fp32",
    speech_encoder: "fp32",
    language_model: "q4f16",
    conditional_decoder: "fp32",
  },
  wasm: {
    embed_tokens: "fp32",
    speech_encoder: "fp32",
    language_model: "q4",
    conditional_decoder: "fp32",
  },
};

let model = null;
let processor = null;
let loadPromise = null;

/* ---- Speaker-embedding cache (keyed by ref-audio URL) ---- */
const speakerCache = new Map();

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

/** Fetch + decode WAV reference audio, returning Float32Array. */
async function fetchRefAudio(url) {
  if (!url) return null;
  const resp = await fetch(url);
  const buf = await resp.arrayBuffer();
  return decodeWav(buf);
}

/**
 * Encode reference audio into speaker embeddings and cache them.
 * Returns the speaker-embedding object ({ ... tensors ... }) for generate().
 */
async function encodeSpeaker(refAudioUrl) {
  if (!refAudioUrl) return null;
  if (speakerCache.has(refAudioUrl)) return speakerCache.get(refAudioUrl);

  const audioData = await fetchRefAudio(refAudioUrl);
  if (!audioData) return null;

  const audioTensor = new Tensor("float32", audioData, [1, audioData.length]);
  const embeddings = await model.encode_speech(audioTensor);
  speakerCache.set(refAudioUrl, embeddings);
  return embeddings;
}

/* ==== Model lifecycle ==== */

async function ensureModel() {
  if (model && processor) return true;
  if (loadPromise) { await loadPromise; return !!(model && processor); }

  loadPromise = (async () => {
    let device = "webgpu";
    let dtype = DTYPE_CONFIGS.webgpu;
    try {
      /* Probe WebGPU availability */
      if (!self.navigator || !self.navigator.gpu) throw new Error("No WebGPU");
      const adapter = await self.navigator.gpu.requestAdapter();
      if (!adapter) throw new Error("No GPU adapter");
    } catch (_) {
      device = "wasm";
      dtype = DTYPE_CONFIGS.wasm;
    }

    try {
      self.postMessage({ status: "device", device });
      model = await ChatterboxModel.from_pretrained(MODEL_ID, {
        device,
        dtype,
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
      /* If WebGPU failed, try WASM fallback */
      if (device === "webgpu") {
        console.warn("[Chatterbox] WebGPU failed, trying WASM:", err);
        device = "wasm";
        dtype = DTYPE_CONFIGS.wasm;
        try {
          self.postMessage({ status: "device", device: "wasm" });
          model = await ChatterboxModel.from_pretrained(MODEL_ID, {
            device: "wasm",
            dtype,
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
        } catch (err2) {
          self.postMessage({ status: "error", message: "Failed to load Chatterbox: " + err2.message });
          return;
        }
      } else {
        self.postMessage({ status: "error", message: "Failed to load Chatterbox: " + err.message });
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

    /* Encode speaker from reference audio (cached after first call) */
    const speakerEmbeddings = await encodeSpeaker(referenceAudioUrl);

    /* Tokenize text */
    const inputs = await processor._call(text);

    /* Generate waveform */
    const genArgs = {
      ...inputs,
      exaggeration,
      max_new_tokens: 256,
    };
    if (speakerEmbeddings) Object.assign(genArgs, speakerEmbeddings);

    const waveform = await model.generate(genArgs);

    const raw = waveform.data || waveform;
    const samples = raw instanceof Float32Array ? raw : new Float32Array(raw);
    const blob = encodeWav(samples);
    const url = URL.createObjectURL(blob);

    self.postMessage({ status: "complete", audio: url });
  } catch (err) {
    self.postMessage({ status: "error", message: err.message || String(err) });
  }
};
