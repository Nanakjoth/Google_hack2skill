# Agentic Tele-Triage Portal — Frontend

Plain HTML/CSS/JS. No build step, no framework, no npm install.

## Run it

1. Make sure the backend is running first (see `../backend/README.md`) —
   you should see it listening on http://localhost:8000
2. Open `index.html` directly in a browser, **or** serve it locally if your
   browser blocks the fetch calls from a `file://` page:
   ```
   cd frontend
   python -m http.server 5500
   ```
   then visit http://localhost:5500

## Connecting to a different backend later

Edit `config.js` — change `API_BASE` to wherever you deploy the backend.
Nothing else in the frontend needs to change.

## Files

- `index.html` — markup and the 4 dashboard views
- `styles.css` — all styling, light/dark theme aware
- `config.js` — the one line you edit when you deploy
- `app.js` — every call to the backend API, and all rendering
