# Content Automation Pipeline

Fully automated Reels/Shorts generator.
**Stack:** DeepSeek V3 → ElevenLabs → Pexels → Creatomate → Buffer

## Setup (15 minutes)

```bash
# 1. Clone and install
git clone <your-repo>
cd content-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in all keys in .env

# 3. Test run (no publishing)
python -m src.pipeline --niche finance --dry-run

# 4. Real run
python -m src.pipeline --niche finance

# 5. Story channel
python -m src.pipeline --niche story
```

## Deploy to Railway (free)

1. Push to GitHub
2. New project on railway.app → Deploy from GitHub
3. Add all env vars from `.env.example` in Railway dashboard
4. Add a Cron job: `0 3 * * *` → `python -m src.pipeline --niche finance`
5. Second Cron: `0 4 * * *` → `python -m src.pipeline --niche story`

## Monitoring

```bash
# Check recent runs
python -c "
from src.storage.run_tracker import RunTracker
from pathlib import Path
t = RunTracker(Path('data/runs.db'))
for r in t.recent_runs(10):
    print(r['status'], r['topic'], r['started_at'])
print('Success rate:', t.success_rate())
"
```

## Cost breakdown (30 videos/month)

| Tool        | Cost      |
|-------------|-----------|
| DeepSeek V3 | ~₹2/mo    |
| ElevenLabs  | Free tier |
| Pexels      | Free      |
| Creatomate  | ~₹500/mo  |
| Cloudinary  | Free tier |
| Buffer      | Free tier |
| Railway     | Free tier |
| **Total**   | **~₹502/mo** |
