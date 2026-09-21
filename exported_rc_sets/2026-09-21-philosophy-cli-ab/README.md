# Philosophy hard CLI A/B

Controlled real-generation comparison using the exact same unused seed and
identical copies of the production corpus baseline.

- Seed ID: `b208e303-6a7c-4d26-9f4f-716742e027ab`
- Title: “Are Doctors Heroes?”
- URL: https://www.thenewatlantis.com/practicing-medicine/are-doctors-heroes
- Stored labels: philosophy / conceptual essay; source kind `idea_essay`
- Tier: hard
- Policy: `cat-pyq-f4` (registered seed-fidelity policy)
- Effort: `low` for both Claude CLI and OpenAI CLI
- RNG seed: `20260921`

Each lane runs against its own database snapshot created before either run.
The shared RAG seed is intentionally not marked used because these are
comparison artifacts, not additions to the production corpus. Normal gates,
Luna checks, similarity screening and per-tier spending limits remain active.

## Results

- Claude CLI export: `claude-RC-HARD-260920-0106.txt`
- OpenAI CLI export: `openai-RC-HARD-260920-0106.txt`
- Detailed controls and measurements: `comparison.md`

Both database copies assigned the same internal RC ID because they began from
the same baseline. The filename prefixes distinguish the providers. Neither
set was written back to the production corpus, and the shared seed remains
unused there.
