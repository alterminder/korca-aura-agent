/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      zIndex: {
        '60': '60',
      },
      colors: {
        app: {
          bg:          'rgb(249, 250, 255)',
          sidebar:     'transparent',
          drawer:      'rgb(249, 250, 255)',
          'nav-text':  'rgb(100, 116, 139)',
          'nav-hover': 'rgb(236, 244, 253)',
          accent:      'rgb(14, 116, 144)',
          'accent-bg': 'rgb(230, 247, 251)',
          panel:       'rgb(255, 255, 255)',
          border:      'rgb(228, 237, 247)',
        },
      },
    },
  },
  plugins: [],
}
