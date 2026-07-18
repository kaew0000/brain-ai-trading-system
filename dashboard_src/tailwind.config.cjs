/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: { DEFAULT: '#0a0a12', 1: '#10101e', 2: '#16162a', 3: '#1e1e38' },
        border:  { DEFAULT: '#1e1e3a', bright: '#2a2a5a' },
        accent: { gold:'#fbbf24',green:'#10b981',red:'#ef4444',blue:'#3b82f6',cyan:'#06b6d4',purple:'#8b5cf6',orange:'#f97316' },
        text: { primary:'#e2e8f0', secondary:'#94a3b8', muted:'#475569' },
      },
      fontFamily: { mono: ['JetBrains Mono','Fira Code','monospace'] },
      animation: { 'pulse-slow':'pulse 3s ease-in-out infinite', 'blink':'blink 1s step-end infinite' },
      keyframes: { blink:{'0%,100%':{opacity:'1'},'50%':{opacity:'0'}} },
      backgroundImage: { 'grid':"linear-gradient(rgba(59,130,246,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,0.03) 1px,transparent 1px)" },
      backgroundSize: { 'grid':'40px 40px' },
    },
  },
  plugins: [],
}
