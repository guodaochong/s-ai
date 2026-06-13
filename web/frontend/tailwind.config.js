/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        accent: '#00d4ff',
        accent2: '#7c3aed',
        accent3: '#10b981',
        warn: '#f59e0b',
        danger: '#ef4444',
        'bg-deep': '#060a13',
        'bg-panel': 'rgba(13,19,33,.92)',
        'bg-card': 'rgba(22,33,52,.75)',
        'bg-input': '#0a0f1c',
        'border-solid': '#1e293b',
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      borderRadius: {
        'DEFAULT': '12px',
        'sm': '8px',
      },
    },
  },
  plugins: [],
}

