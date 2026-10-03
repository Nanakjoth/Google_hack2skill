// Where the console looks for the API.
//
// Same-origin by default, and that is the correct answer for every deployment
// that matters: main.py serves frontend/ from this same FastAPI app, so the
// console and the API are one URL and there is nothing to configure.
//
// The absolute `http://localhost:8000` that used to be hardcoded here was only
// ever true on the machine running `uvicorn`. Deployed on Cloud Run it sent
// every request to the *visitor's own* localhost, where nothing was listening,
// so the console reported "Backend unreachable" while the API was perfectly
// healthy - a misleading symptom that points at the server instead of at this
// file. Relative paths also keep CORS out of the picture entirely, which is why
// ALLOWED_ORIGINS=none is safe to deploy.
//
// Set the override below only if you deliberately host the console somewhere
// other than the API - doing so reintroduces the CORS requirement.
const API_BASE_OVERRIDE = null;

// Opened straight off disk (file://) there is no origin for a relative path to
// resolve against, so fall back to the local dev server. That is the one case
// that genuinely needs an absolute URL.
const API_BASE = API_BASE_OVERRIDE !== null
  ? API_BASE_OVERRIDE
  : (location.protocol === 'file:' ? 'http://localhost:8000' : '');