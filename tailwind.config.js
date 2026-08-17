/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./reception/**/*.py",
    "./triage/**/*.py",
    "./doctor/**/*.py",
    "./pharmacy/**/*.py",
    "./billing/**/*.py",
    "./static/js/**/*.js",
    "./static/src/**/*.css"
  ],
  safelist: [
    'portal-reception',
    'portal-triage',
    'portal-doctor',
    'portal-pharmacy',
    'portal-billing',
    'nav-active',
    'accent-dot',
    'accent-badge',
    'accent-surface',
    'accent-surface-light',
    'brand-logo',
    'operator-avatar',
    'status-dot',
    'queue-badge',
    'header-accent',
    'sidebar-accent-bg',
  ],
  theme: {
    extend: {
      colors: {
        // High-contrast, crisp dark typography palette (NO washed-out dull greys)
        slate: {
          50: '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#cbd5e1',
          400: '#64748b',  // Readable medium slate
          500: '#475569',  // Deep readable slate
          600: '#334155',  // High contrast slate
          700: '#1e293b',  // Bold dark slate
          800: '#0f172a',  // Rich dark navy-black
          850: '#0b1120',
          900: '#020617',  // Deepest black-slate
          950: '#000000',
        },
        neutral: {
          50: '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          400: '#737373',
          500: '#525252',
          600: '#404040',
          700: '#262626',
          800: '#171717',
          900: '#0a0a0a',
          950: '#000000',
        },
        urgency: {
          normal: '#475569',
          urgent: '#d97706',
          emergency: '#dc2626'
        }
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        serif: ['"Newsreader"', 'Georgia', 'Cambria', 'serif']
      }
    },
  },
  plugins: [],
}
