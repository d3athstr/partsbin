/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ISA-101 / High-Performance HMI dark palette.
        // Gray when OK — color is reserved for abnormal states + interaction.
        dark: {
          bg: '#0f1419',
          surface: '#1a1f26',
          elevated: '#252d36',
          border: '#3c4043',
          text: '#e8eaed',
          textMuted: '#9aa0a6',
          accent: '#8ab4f8',       // blue = interactive only
          accentHover: '#aecbfa',
          error: '#f28b82',        // red = alarm (out of stock, dead token)
          warning: '#fdd663',      // amber = warning (low stock, needs review)
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
