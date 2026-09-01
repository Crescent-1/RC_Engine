# RC Engine — public read-only demo

A static walkthrough of the engine: corpus stats, the seven-gate rejection
cascade, and a per-set explorer (passage, novelty audit, blueprint, verification).

**It is completely inert.** No backend, no API key, no model call, nothing that
can start a generation run or spend money. The page reads JSON files that were
baked out of `rc_pipeline.db` at build time.

```
demo/
  index.html          markup + all prose copy
  css/demo.css        design system, dark + light
  js/demo.js          renders the snapshot, no dependencies
  data/               GENERATED — do not hand-edit
    corpus.json         headline stats, tier table, slot coverage
    funnel.json         the gate cascade
    sets.json           one card per set (metadata only)
    sets/<RC_ID>.json   per-set detail
```

## Rebuilding the snapshot

Run after any batch of new sets, then commit `demo/data/`:

```bash
python tools/build_demo_snapshot.py
```

The builder opens the DB **read-only** and prints a summary. Two lines matter:

- `composite check` — it recomputes each set's novelty composite from the
  published channel bars and compares against what the engine stored. If this
  warns, the channel maths in `tools/build_demo_snapshot.py` has drifted from
  `NoveltyScorer._composite` and the bars on the page are lying. Fix before deploying.
- `WARNING unparsed rc_text` — a set whose stored text didn't match the engine's
  output contract. It degrades to metadata-only rather than breaking the build.

## What is withheld

Redaction is on by default and enforced in the builder, not the page:

| Withheld | Why |
|---|---|
| `*_cost_usd`, `*_tokens` | per-set economics stay private |
| `provider` | no model vendor names |
| Gate thresholds | never exported; only outcomes are |
| Passage + answer key | published **only** for the allowlist (see below) |

`--include-costs` exists for local inspection. Never deploy a snapshot built
with it; the page footer would also then claim more than it should.

## Choosing which passages go public

**This is a judgement call about your delivery contract, not a technical one.**
Every engine set in the DB was exported to the client, so publishing any passage
in full means publishing a delivered asset.

The default is the single oldest approved set — most likely already through the
client's mock cycle, so the least live. Change it deliberately:

```bash
python tools/build_demo_snapshot.py --full-text RC-HARD-260726-0021
python tools/build_demo_snapshot.py --full-text "RC_E_0706_1,RC-HARD-260712-0009"
```

Sets outside the allowlist still contribute everything analytical — scores,
blueprint, all eight audit channels, judge rubric, solver answers. Only the prose
and answer key are held back, and the page says so plainly. The demo works well
with exactly one passage published; more is not better here.

## Deploying

The site is pure static files. `demo/` is the publish directory — there is no
build step and no `npm`.

**Cloudflare Pages (recommended).** Works with a private repo on the free plan,
which GitHub Pages does not.

1. Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git
2. Pick `Crescent-1/RC_Engine`
3. Build command: *(leave empty)* · Build output directory: `demo`
4. Deploy, then add a custom domain if you want one

Every push to `master` that touches `demo/` redeploys.

**GitHub Pages.** `.github/workflows/deploy-demo.yml` publishes `demo/` on push.
Enable Settings → Pages → Source: GitHub Actions. Note that Pages on a *private*
repo requires a paid GitHub plan; Cloudflare has no such restriction.

**Local preview.** The page fetches JSON, so `file://` will not work — it must be
served over http:

```bash
python -m http.server 8736 --directory demo
```

## Before the first public deploy

- [ ] Decide the `--full-text` allowlist against your contract terms
- [ ] Confirm the repo's own visibility is what you intend — connecting a Git
      provider publishes `demo/`, but the repo keeps whatever visibility it has,
      and the full engine source lives alongside it
- [ ] Rebuild the snapshot and confirm `composite check` passes
- [ ] Confirm `costs_included` is `false` in `demo/data/corpus.json`
