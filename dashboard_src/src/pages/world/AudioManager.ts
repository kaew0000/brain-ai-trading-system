// ============================================================
// Brain Bot V15 — Audio Manager
// Generates all sounds procedurally using the Web Audio API.
// No audio files. Toggleable via Zustand audioEnabled flag.
// ============================================================

import { useWorldStore } from './worldStore';

let _ctx: AudioContext | null = null;
let _masterGain: GainNode | null = null;
let _ambientNodes: OscillatorNode[] = [];
let _enabled = false;
let _storeUnsub: (() => void) | null = null;

// ── AudioContext factory ──────────────────────────────────────

function getCtx(): AudioContext {
  if (!_ctx) {
    _ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
  if (_ctx.state === 'suspended') _ctx.resume();
  return _ctx;
}

function getMaster(): GainNode {
  if (!_masterGain) {
    const ctx = getCtx();
    _masterGain = ctx.createGain();
    _masterGain.gain.value = _enabled ? 0.15 : 0;
    _masterGain.connect(ctx.destination);
  }
  return _masterGain;
}

// ── Ambient drones ────────────────────────────────────────────

function startAmbient(): void {
  const ctx = getCtx();
  const master = getMaster();
  stopAmbient();

  // Low server hum (60 Hz + harmonics)
  const freqs = [60, 120, 180, 240];
  for (const freq of freqs) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.value = 0.015 / freqs.length;
    osc.connect(gain);
    gain.connect(master);
    osc.start();
    _ambientNodes.push(osc);
  }

  // High-pitched office hum (2.4 kHz subtle)
  const hvac = ctx.createOscillator();
  const hvacGain = ctx.createGain();
  hvac.type = 'sine';
  hvac.frequency.value = 2400;
  hvacGain.gain.value = 0.002;
  hvac.connect(hvacGain);
  hvacGain.connect(master);
  hvac.start();
  _ambientNodes.push(hvac);
}

function stopAmbient(): void {
  for (const osc of _ambientNodes) {
    try { osc.stop(); osc.disconnect(); } catch { /* already stopped */ }
  }
  _ambientNodes = [];
}

// ── Room ambience (interior "music" swap on door transitions) ───
// Layers a lowpass filter + a room-flavored gentle tone on top of
// the base ambient drones so each interior reads distinctly without
// needing separate audio files.

let _roomFilter: BiquadFilterNode | null = null;
let _roomToneOsc: OscillatorNode | null = null;
let _roomToneGain: GainNode | null = null;

interface RoomTone { cutoff: number; toneFreq: number; toneGain: number; }

const ROOM_TONES: Record<string, RoomTone> = {
  default:     { cutoff: 8000, toneFreq: 440, toneGain: 0.0 },
  ceo:         { cutoff: 5000, toneFreq: 220, toneGain: 0.006 },
  server:      { cutoff: 9000, toneFreq: 880, toneGain: 0.01 },
  data_center: { cutoff: 9000, toneFreq: 660, toneGain: 0.008 },
  ml_lab:      { cutoff: 6000, toneFreq: 523, toneGain: 0.007 },
  intelligence:{ cutoff: 6000, toneFreq: 349, toneGain: 0.006 },
  emergency:   { cutoff: 4000, toneFreq: 130, toneGain: 0.012 },
  teleport:    { cutoff: 9500, toneFreq: 990, toneGain: 0.009 },
};

function ensureRoomToneNodes(): void {
  if (_roomFilter && _roomToneOsc && _roomToneGain) return;
  const ctx = getCtx();
  const master = getMaster();

  _roomFilter = ctx.createBiquadFilter();
  _roomFilter.type = 'lowpass';
  _roomFilter.frequency.value = 8000;
  _roomFilter.connect(master);

  _roomToneGain = ctx.createGain();
  _roomToneGain.gain.value = 0;
  _roomToneGain.connect(_roomFilter);

  _roomToneOsc = ctx.createOscillator();
  _roomToneOsc.type = 'sine';
  _roomToneOsc.frequency.value = 440;
  _roomToneOsc.connect(_roomToneGain);
  _roomToneOsc.start();
}

/** Called when the player enters a building interior (a "door" event). */
export function setInteriorAmbience(roomId: string): void {
  if (!_enabled) return;
  ensureRoomToneNodes();
  const tone = ROOM_TONES[roomId] ?? ROOM_TONES.default;
  const ctx = getCtx();
  const now = ctx.currentTime;
  _roomFilter!.frequency.cancelScheduledValues(now);
  _roomFilter!.frequency.linearRampToValueAtTime(tone.cutoff, now + 0.6);
  _roomToneOsc!.frequency.cancelScheduledValues(now);
  _roomToneOsc!.frequency.linearRampToValueAtTime(tone.toneFreq, now + 0.6);
  _roomToneGain!.gain.cancelScheduledValues(now);
  _roomToneGain!.gain.linearRampToValueAtTime(tone.toneGain, now + 0.8);
}

/** Called when the player exits back to the outdoor plaza. */
export function setExteriorAmbience(): void {
  if (!_enabled) return;
  ensureRoomToneNodes();
  const ctx = getCtx();
  const now = ctx.currentTime;
  _roomFilter!.frequency.cancelScheduledValues(now);
  _roomFilter!.frequency.linearRampToValueAtTime(9000, now + 0.6);
  _roomToneGain!.gain.cancelScheduledValues(now);
  _roomToneGain!.gain.linearRampToValueAtTime(0, now + 0.8);
}

// ── One-shot SFX ─────────────────────────────────────────────

/** Short beep for UI interaction */
export function playBeep(freq = 880, duration = 0.06, volume = 0.08): void {
  if (!_enabled) return;
  const ctx = getCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'square';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(volume, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + duration);
}

/** Footstep click */
export function playFootstep(): void {
  if (!_enabled) return;
  const ctx = getCtx();
  // White noise burst
  const bufferSize = ctx.sampleRate * 0.04;
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

  const src = ctx.createBufferSource();
  src.buffer = buffer;
  const gain = ctx.createGain();
  const filter = ctx.createBiquadFilter();
  filter.type = 'bandpass';
  filter.frequency.value = 300;
  gain.gain.setValueAtTime(0.04, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.04);
  src.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);
  src.start();
}

/** Modal open chime (ascending 3-note) */
export function playModalOpen(): void {
  if (!_enabled) return;
  const ctx = getCtx();
  const notes = [440, 554, 659];
  notes.forEach((freq, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.value = freq;
    const t = ctx.currentTime + i * 0.07;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.08, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.2);
  });
}

/** Alert sound for system critical */
export function playAlert(): void {
  if (!_enabled) return;
  const ctx = getCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'sawtooth';
  osc.frequency.setValueAtTime(220, ctx.currentTime);
  osc.frequency.linearRampToValueAtTime(440, ctx.currentTime + 0.2);
  osc.frequency.linearRampToValueAtTime(220, ctx.currentTime + 0.4);
  gain.gain.setValueAtTime(0.1, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.4);
}

/** Keyboard typing tick */
export function playKeyTick(): void {
  if (!_enabled) return;
  const ctx = getCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'square';
  osc.frequency.value = 1200 + Math.random() * 400;
  gain.gain.setValueAtTime(0.03, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.025);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.025);
}

/** Teleport whoosh */
export function playTeleport(): void {
  if (!_enabled) return;
  const ctx = getCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(800, ctx.currentTime);
  osc.frequency.exponentialRampToValueAtTime(200, ctx.currentTime + 0.3);
  gain.gain.setValueAtTime(0.12, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.3);
}

// ── Lifecycle ─────────────────────────────────────────────────

export function initAudio(): void {
  // Subscribe to audioEnabled toggle in store
  _storeUnsub = useWorldStore.subscribe(
    (s) => s.audioEnabled,
    (enabled) => {
      _enabled = enabled;
      if (_masterGain) {
        _masterGain.gain.setTargetAtTime(enabled ? 0.15 : 0, getCtx().currentTime, 0.5);
      }
      if (enabled) {
        startAmbient();
      } else {
        stopAmbient();
      }
    },
  );
}

export function destroyAudio(): void {
  stopAmbient();
  _storeUnsub?.();
  _storeUnsub = null;
  try { _roomToneOsc?.stop(); _roomToneOsc?.disconnect(); } catch { /* ignore */ }
  _roomFilter = null;
  _roomToneOsc = null;
  _roomToneGain = null;
  try { _ctx?.close(); } catch { /* ignore */ }
  _ctx = null;
  _masterGain = null;
}
