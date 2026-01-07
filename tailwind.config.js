/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        'ntu-red': '#C20430',
        'ntu-blue': '#1D4F91',
        'status-green': '#10B981',
        'status-amber': '#F59E0B',
        'status-red': '#EF4444',
      },
    },
  },
  plugins: [],
}
