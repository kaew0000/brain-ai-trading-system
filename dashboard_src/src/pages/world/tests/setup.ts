// ============================================================
// Vitest test setup — mocks browser APIs unavailable in jsdom
// ============================================================

import { vi } from 'vitest';

// Mock Web Audio API
class MockAudioContext {
  sampleRate = 44100;
  currentTime = 0;
  state = 'running';
  destination = {} as any;
  createOscillator() {
    return {
      type: 'sine' as OscillatorType,
      frequency: { value: 440, setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
      connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn(),
      onended: null,
    };
  }
  createGain() {
    return {
      gain: { value: 1, setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn(), setTargetAtTime: vi.fn() },
      connect: vi.fn(), disconnect: vi.fn(),
    };
  }
  createBiquadFilter() {
    return { type: 'lowpass', frequency: { value: 350 }, connect: vi.fn(), disconnect: vi.fn() };
  }
  createBuffer(channels: number, length: number, sampleRate: number) {
    return {
      getChannelData: () => new Float32Array(length),
      sampleRate, duration: length / sampleRate, length, numberOfChannels: channels,
    };
  }
  createBufferSource() {
    return { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn(), onended: null };
  }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

Object.defineProperty(window, 'AudioContext', { value: MockAudioContext, writable: true });
Object.defineProperty(window, 'webkitAudioContext', { value: MockAudioContext, writable: true });

// Mock HTMLCanvasElement.getContext
const originalGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(
  contextId: string,
  ...args: any[]
): any {
  if (contextId === '2d') {
    return {
      fillStyle: '',
      strokeStyle: '',
      globalAlpha: 1,
      font: '',
      textAlign: 'left' as CanvasTextAlign,
      fillRect: vi.fn(),
      strokeRect: vi.fn(),
      clearRect: vi.fn(),
      fillText: vi.fn(),
      strokeText: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      arc: vi.fn(),
      closePath: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      drawImage: vi.fn(),
      measureText: () => ({ width: 10 }),
      getImageData: () => ({ data: new Uint8ClampedArray(4) }),
      putImageData: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      scale: vi.fn(),
      translate: vi.fn(),
      rotate: vi.fn(),
      setTransform: vi.fn(),
      createLinearGradient: () => ({ addColorStop: vi.fn() }),
      createRadialGradient: () => ({ addColorStop: vi.fn() }),
    };
  }
  return originalGetContext.call(this, contextId, ...args);
};
