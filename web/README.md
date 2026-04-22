# web/

Static assets for the apexos.app front door.

## apexos-landing.html

Marketing landing page for APEX OS. Primary CTAs are wired to `https://apexos.streamlit.app/`.

**Serving options:**

1. **Static host** — Drop `apexos-landing.html` at the root of any static host (Netlify, GitHub Pages, Cloudflare Pages) and point `apexos.app` at it. No build step required.

2. **Inside Streamlit** — Set `APEXOS_SHOW_LANDING=true` before launching the app. `app_landing.py` reads this file and renders it via `st.components.v1.html` before the main board UI appears.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `APEXOS_SHOW_LANDING` | unset / `false` | When `true`, renders the landing page as the first screen inside the Streamlit app |
