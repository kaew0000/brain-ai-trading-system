import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },

  // Phaser needs special handling for tree-shaking
  optimizeDeps: {
    include: ['phaser'],
  },

  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // UI framework core
          'ui-vendor': ['react', 'react-dom', 'react-router-dom', 'zustand'],
          // Animation library (large, used on subset of routes)
          'animation-vendor': ['framer-motion'],
          // Phaser game engine (always separate)
          // Separate Phaser into its own chunk (~4MB)
          phaser: ['phaser'],
          // React + framer in another
          'react-vendor': ['react', 'react-dom', 'framer-motion', 'zustand'],
        },
      },
    },
    // Phaser is large — increase warning threshold
    chunkSizeWarningLimit: 5000,
  },

  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to FastAPI backend in dev
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
