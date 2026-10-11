P8 frontend detail verification

- Controlled acceptance (configured setup/build/tests): NOT_RUN.
- Frontend npm run lint: NOT_RUN.
- Frontend npm test: NOT_RUN.
- Frontend npm run build: NOT_RUN.
- Browser interactions, keyboard accessibility and responsive layout: NOT_RUN.

Patch generation has no execution or browser access. Existing tests and controlled
acceptance configuration are preserved. Added tests cover routing, history range
boundaries, missing/zero prices, detail rendering and API request contracts.

Before acceptance, run the configured controlled acceptance and npm checks.
In a browser verify direct links, back/forward, all filters, failed refresh feedback,
stop/start, deletion cancellation/confirmation, dashboard updates, keyboard focus,
and narrow-screen chart layout. Delete uses the browser's explicit confirmation dialog.
