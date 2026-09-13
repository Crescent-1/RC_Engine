# Passage Works website

Client-facing marketing site for the RC Gen project. Open `index.html` through a local HTTP server. No package installation or paid generation is needed.

The website uses only its own HTML, CSS, JavaScript and assets. The sample passage is a newly authored website demonstration, not a client deliverable. Business name, contact and starting prices are carried over from the existing website; confirm them before sharing externally.

`node build.mjs` copies an explicit public-file allowlist into `dist/`. It never copies the engine, database, environment files, client exports or the existing standalone technical page. It does not delete files. Hosting uses an isolated source repository so project history is not uploaded.

Enquiry forms prepare an email in the visitor's email application. They do not submit or store leads. A direct email link and copyable brief remain available. Theme preferences are stored only in the visitor's browser.
