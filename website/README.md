# Passage Works website

Client-facing marketing site for the RC Gen project. Open `index.html` through a local HTTP server. No package installation or paid generation is needed.

The website uses only its own HTML, CSS, JavaScript and assets. The sample passage is a newly authored website demonstration, not a client deliverable. Business name, contact and starting prices are carried over from the existing website; confirm them before sharing externally.

`node build.mjs` copies an explicit public-file allowlist into `dist/`. It never copies the engine, database, environment files, client exports or the existing standalone technical page. It does not delete files. Hosting uses an isolated source repository so project history is not uploaded.

To count visits in Google Analytics 4, create a web data stream for `https://passageworks.in/`, then build with its Measurement ID: `$env:GA4_MEASUREMENT_ID='G-XXXXXXXXXX'; node build.mjs --require-analytics` in PowerShell. The build inserts Google's tag into the public `dist/index.html`; it does not put the ID into the source page. Deploy the built `dist/` to the existing Netlify site. In GA4, check Realtime after visiting the live page. The tag records standard page views; enquiry form contents are not sent as analytics events. Builds without the ID still work for local preview, while `--require-analytics` prevents an accidental production build without tracking.

Enquiry forms prepare an email in the visitor's email application. They do not submit or store leads. A direct email link and copyable brief remain available. Theme preferences are stored only in the visitor's browser.
