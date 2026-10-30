# Pre-hackathon checklist

## Thursday before the webinar (4pm KSA)
- [ ] Unzip kit, `git init`, push to a **private** GitHub repo (check rules before making anything public — NDA)
- [ ] `make setup`, then `make smoke` and `make test` pass on your laptop
- [ ] Claude Code installed and logged into the **Team** account; run it once inside this repo so it reads CLAUDE.md
- [ ] Check your Team seat type and usage (Premium vs Standard) so you know your limits
- [ ] API keys ready and tested with one call each:
  - [ ] OpenAI-compatible key (OpenAI / Groq / Together) — fallback model
  - [ ] Anthropic API key (separate from your Claude Team chat plan — API is billed separately)
  - [ ] Hugging Face token (embeddings / open models)
  - [ ] AWS credentials if you might deploy (Bedrock / Lambda)
  - [ ] Any HUMAIN / ALLaM access they provide (likely announced at the webinar)
- [ ] Billing limits set on every key so a bug can't burn money
- [ ] Python 3.11+, Node 20+, git, Docker (optional), `uv` or venv working
- [ ] Pre-download common models you might use offline (e.g. a multilingual embedding model like `intfloat/multilingual-e5-base`)
- [ ] Screen recorder ready (backup demo video), slides template open
- [ ] Sleep plan + food for Fri/Sat. Seriously.

## Questions to get answered at the webinar
- [ ] Exact deliverables: repo link? notebook? video? slides? deadline time and timezone?
- [ ] Which models/APIs are allowed? Are external APIs allowed or HUMAIN-only? Any compute provided?
- [ ] How are held-out test cases run — do they run our code (need a fixed `predict` entrypoint/CLI) or do we submit predictions?
- [ ] Input/output format and official metric for each challenge
- [ ] Is there a public leaderboard? Submission limits per day?
- [ ] Presentation: live or recorded? length? who presents (shortlist only)?
- [ ] Can we use pre-written template code like this harness? (usually yes — confirm)
- [ ] Rules on open-source code, pretrained models, data augmentation, external data

## During the hackathon — every version
1. New named system → 2. `make eval SYS=... NOTE="..."` → 3. `make compare` → 4. one line in DECISIONS.md → 5. git commit with the run_id in the message.
