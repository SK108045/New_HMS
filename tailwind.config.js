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
        // Pure neutral Light Black & Light Grey system (ZERO blue tint)
        slate: {
          50: '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#3f3f46',
          800: '#27272a',  // Light Black / Charcoal
          850: '#202023',  // Refined Light Black
          900: '#18181b',  // Pure Neutral Light Black
          950: '#09090b',  // Dark Black
        },
        neutral: {
          50: '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          400: '#a3a3a3',
          500: '#737373',
          600: '#525252',
          700: '#404040',
          800: '#262626',
          900: '#171717',
          950: '#0a0a0a',
        },
        urgency: {
          normal: '#71717a',
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
