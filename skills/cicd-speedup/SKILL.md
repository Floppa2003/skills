---
name: cicd-speedup
description: 'Ordered playbook for cutting CI/CD time on Python + Docker + GitHub Actions stacks (real run from ~6-7min to ~40-50s, no infra spend). Use whenever the user complains about slow CI, slow builds, slow deploys, slow tests, or container/uvicorn boot time — including casual phrasings like "CI медленный", "деплой долго", "пайплайн тормозит", "почему билд так долго", "ускорить GitHub Actions", "uv vs pip", "BuildKit cache", "self-hosted runner медленный", "uvicorn долго стартует", "почему deploy 5 минут".'
---

# CI/CD Speedup Playbook

Concrete, ordered moves for cutting wall-clock time on Python + Docker + GitHub Actions pipelines. Distilled from a real run that went from ~6-7min to ~40-50s (~8-9×) with no infra spend, no rewrites, no special tools.

This is a **lens + ordered checklist**, not a theoretical treatise. Apply in order — early steps are free and big, later steps are riskier and project-specific.

## How to apply

1. **Measure first.** Don't propose changes before pulling actual step-level timings. The single biggest step is the first target; everything else is noise.
2. **Apply the ordered playbook.** Cache wins → parallelize → tighten health checks → lazy-load imports. Order matters — caching is free, parallelization is hardware-dependent, code changes need profiling.
3. **Name what NOT to do.** Anti-patterns burn weeks. Surface them proactively when the user proposes them (esp. `prune -af`, instance bumping, blind lazy-loading, `--keep-storage` with `until` filter).
4. **Quantify the win.** Every recommendation should come with an estimated saving in seconds, anchored in the playbook's measured numbers, so the user can prioritize.

## TL;DR — apply in this order

1. **Order Dockerfile layers** so heavy `pip install` is cached separately from source code. (One-time, free, biggest single win on rebuilds.)
2. **Switch pip → uv** in CI installs. ~5–10× faster, drop-in replacement.
3. **Mount BuildKit cache for `~/.cache/uv`** in your Dockerfile so the wheel cache survives rebuilds on a self-hosted runner.
4. **Parallelize independent deploy steps.** Most "deploy A, then B, then C" sequences have zero runtime dependency — fan them out.
5. **Right-size health-check loops.** `sleep 5` is almost always overshoot; tail logs for the ready signal instead of polling HTTP.
6. **Cap the BuildKit cache** with `--keep-storage` so it doesn't fill the disk over months.
7. **Lazy-load heavy imports** that aren't needed at boot. Profile first; the candidates are usually obvious.

---

## 0. Methodology — measure before optimizing

### 0.1 Pull step-level timings from GitHub Actions

```bash
gh run view <run-id> --json status,conclusion,jobs,createdAt,updatedAt | python3 -c "
import json, sys
from datetime import datetime
d = json.load(sys.stdin)
total = (datetime.fromisoformat(d['updatedAt'].replace('Z','+00:00'))
       - datetime.fromisoformat(d['createdAt'].replace('Z','+00:00'))).total_seconds()
print(f'=== {d[\"conclusion\"]}  total={total:.0f}s ===')
for j in d['jobs']:
    print(f'-- {j[\"name\"]}: {j.get(\"conclusion\")} --')
    for s in j.get('steps', []):
        sst, sct = s.get('startedAt'), s.get('completedAt')
        if sst and sct:
            dur = (datetime.fromisoformat(sct.replace('Z','+00:00'))
                 - datetime.fromisoformat(sst.replace('Z','+00:00'))).total_seconds()
            if dur >= 1: print(f'  {dur:6.1f}s  {s.get(\"name\")}')"
```

Run for the last 5–10 successful runs. Biggest step is your first target.

### 0.2 Read the actual logs of the slowest step

```bash
gh run view <run-id> --log | grep "Deploy" | head -40
```

For health-check loops, find the line where the service became healthy and count back to figure out *why* it took N attempts. If `Attempt 4` succeeded with `uptime=5.2s` and you were sleeping 5s, the container was actually ready ~15s before you noticed. That's free seconds.

### 0.3 Profile import time inside the container

```bash
docker exec <container> python -X importtime -c "import your_app.main" 2>&1 | tail -50
```

Format: `import time: self_µs | cumulative_µs | module`. Cumulative on top-level module = real boot cost. 8+ second cold imports are common; usually 1-2 specific imports you can move into a function body.

### 0.4 Measure prod CPU/memory before deciding worker counts

```bash
docker stats <container> --no-stream
docker exec <container> ps -ef
uptime; free -h
```

If prod sits at 0.2% CPU, you don't need multiple workers. CI verifiers often run a different worker count than prod and pay the boot cost for nothing.

---

## 1. Cache wins — biggest gains, lowest risk

### 1.1 Order Dockerfile layers from least- to most-frequently-changed

Docker invalidates every layer downstream of the first changed file. If `COPY . .` comes before `pip install`, every code change rebuilds Python deps.

```dockerfile
COPY requirements.txt .                 # rarely changes
RUN pip install -r requirements.txt     # heavy, only reruns when ↑ changes
COPY . .                                 # frequent changes, but cheap
```

**Typical result:** dependency layer rebuilds drop from minutes to zero on code-only pushes. Real run: ~150s → ~8s.

If `pyproject.toml`, `poetry.lock`, `setup.py` also pin deps, include them in the same early COPY block.

### 1.2 GitHub Actions: cache pip *before* migrating to uv

Built into `actions/setup-python`:

```yaml
- uses: actions/setup-python@v4
  with:
    python-version: '3.11'
    cache: 'pip'
    cache-dependency-path: requirements.txt
```

Saves a few seconds. The real install (resolver + extraction) is unchanged — that's why §1.4 matters more.

### 1.3 BuildKit cache mount (Docker, self-hosted runners)

Pins a directory across builds *without* baking it into the layer:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.11
RUN pip install --no-cache-dir uv
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt
```

Requirements: `# syntax=docker/dockerfile:1.7` directive, BuildKit enabled (default in Docker 23+), self-hosted runner (cache lives in BuildKit storage on the host).

GitHub-hosted runners are ephemeral — every job is a fresh VM. Cache mount gives you nothing there. Use only for self-hosted.

### 1.4 Switch pip → uv

`uv` (Astral, makers of `ruff`) is a Rust-implemented pip replacement. Drop-in for `requirements.txt` and `pyproject.toml`.

**Why it's fast — and the answer is *not* "better caching":**

| Phase | What it does | Does cache help? |
|---|---|---|
| Download wheels | Network | ✅ Yes |
| **Resolver** (compatible versions across packages) | Lots of pypi API calls | ❌ Not really |
| Wheel extraction | I/O + Python | ❌ No |
| File materialization | pip *copies*, uv *hardlinks* | ❌ No |

uv kills the slow non-cacheable parts: Rust resolver, parallel everything, hardlinks instead of copies.

**In CI:**
```yaml
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true
    cache-dependency-glob: requirements.txt
- run: uv pip install --system -r requirements.txt
```

**In Docker** (combined with §1.3):
```dockerfile
RUN pip install --no-cache-dir uv
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt
```

**Typical result:** test-job `pip install` ~55s → ~9s on the first run with no uv cache yet. Warm cache: ~10s steady-state. Bottleneck shifts elsewhere.

Caveats: `uv pip install --system` writes to system Python (fine in containers, use venv locally). Some packages with custom build steps (PyTorch index-url, etc.) need extra flags.

### 1.5 Cap the BuildKit cache (or it eats your disk)

BuildKit cache, especially with cache mounts, accumulates over months. Eventually you wake up to "no space left on device".

**Run before each build:**
```bash
docker buildx prune --keep-storage=5GB -f
```

Recent layers (your hot uv-cache install layer) survive — fast rebuilds preserved.

**Critical mistake to avoid:**
```bash
# DON'T: nukes EVERYTHING, full rebuild every time
docker buildx prune -af

# DON'T: makes --keep-storage a no-op for the first week
docker buildx prune --keep-storage=5GB --filter until=168h -f
```

The `until=168h` filter means "only consider entries older than 7 days". For week one, *nothing* is eligible, the cap silently doesn't apply, the cache grows past the limit. Real incident: cache reached 6.2 GB before noticed.

**Two-tier cleanup (recommended):**
```bash
docker buildx prune --keep-storage=5GB -f

DISK_USE=$(df --output=pcent / | tr -dc '0-9' | head -c2)
if [ -n "$DISK_USE" ] && [ "$DISK_USE" -gt 85 ]; then
  docker buildx prune --keep-storage=1GB -f       # aggressive
  docker image prune -af --filter until=72h
fi
```

Disk sizing: EBS gp3 ≈ $0.10/GB-month. 50GB ≈ $5/mo, comfortable for most projects with the cap above.

---

## 2. Parallelize the deploy

### 2.1 Map dependencies between deployable units

Draw the graph before parallelizing. Typical multi-service deploy:

```
  Service A (HTTP API)        ←──→  shared database
  Service B (background jobs) ←──→  shared database
  Service C (log shipper)     ─────  no runtime deps
```

If A and B share state through a database (and don't HTTP-call each other), they parallelize. C with no deps obviously parallelizes.

If services *do* HTTP-call each other: deploy bottom-up (callees first), or accept brief cross-service errors during the swap window.

### 2.2 Bash pattern for parallel deploys

```bash
set +e

deploy_a() { set -e; ...; }
deploy_b() { set -e; ...; }
deploy_c() { set -e; ...; }

# Per-function logs so streams don't garble.
deploy_a > /tmp/deploy_a.log 2>&1 & A_PID=$!
deploy_b > /tmp/deploy_b.log 2>&1 & B_PID=$!
deploy_c > /tmp/deploy_c.log 2>&1 & C_PID=$!

A_RC=0; wait "$A_PID" || A_RC=$?
B_RC=0; wait "$B_PID" || B_RC=$?
C_RC=0; wait "$C_PID" || C_RC=$?

echo "=== A log (rc=$A_RC) ==="; cat /tmp/deploy_a.log
echo "=== B log (rc=$B_RC) ==="; cat /tmp/deploy_b.log
echo "=== C log (rc=$C_RC) ==="; cat /tmp/deploy_c.log

[ "$A_RC" -ne 0 ] || [ "$B_RC" -ne 0 ] || [ "$C_RC" -ne 0 ] && exit 1
exit 0
```

Key: `set +e` outer (failed function doesn't kill step before logs collect), `set -e` inner (commands fail fast), per-function `/tmp` files (printed *after* both finish — interleaved logs are unreadable).

### 2.3 Watch out for CPU contention on small instances

Real result on 2-vCPU: parallelizing 3 service starts gave ~13s saved instead of theoretical ~26s. Heaviest service got *slower* under contention.

- **4+ vCPU**: full parallel works as advertised
- **2 vCPU**: parallel still wins, but less than expected
- **1 vCPU**: don't bother parallelizing service boot

Don't bump instance size just for CI bursts. If prod CPU is well under ceiling, accept the 13s and move on.

---

## 3. Health-check probes — stop sleeping 5 seconds

The default everywhere:
```bash
for i in {1..N}; do
  if curl -fsS http://localhost:8000/health; then break; fi
  sleep 5
done
```

Wrong in two ways.

### 3.1 `sleep 5` is almost always overshoot

If service boots in 5s, polling every 5s finds it ready between 5–10s — average 7.5s vs actual 5s ready. **Avg overhead: 2.5s/loop.**

Drop to `sleep 2` (avg overhead: 1s) and raise iteration count *N* proportionally so the timeout window stays the same. For early seconds when service is definitely not ready, `sleep 0.5` works.

### 3.2 Tail logs for a "ready" string instead of polling HTTP

uvicorn prints `"Application startup complete."`. gunicorn: `"Booting worker"`. nginx: `"start worker process"`.

```bash
timeout 60 bash -c '
  docker logs --follow my_container 2>&1 |
    grep -m1 "Application startup complete"
'
```

Reacts within ~50ms of ready, vs up to 2s of polling overshoot.

Caveat: structured (JSON) loggers may transform the ready string — verify by tailing a real boot. Frameworks sometimes print ready *before* lifespan handlers complete; HTTP probing is the safest final confirmation.

**Robust hybrid:**
```bash
# Wait for log signal (fast)
timeout 60 bash -c 'docker logs --follow X 2>&1 | grep -m1 "ready"'
# Confirm /health responds (catches the rare case the log lies)
curl -fsS http://localhost:8001/health
```

### 3.3 Don't double-health-check the same image

Common pattern:
1. `docker run` new image on a side port → health check
2. Stop old prod container
3. Stop side container
4. `docker-compose up` (recreates from same image)
5. Health-check prod container

Step 5 health-checks the *same image* you already validated in step 1. Only the compose config could be wrong.

Either drop step 5's full health check (trust the image, just verify port is bound via `docker exec` or `nc`), or drop step 1 and just compose-up + health-check once. Real run: dropping the second loop saved ~15-20s.

---

## 4. Service-side optimizations (require code changes)

### 4.1 Right-size your worker count

1. Look at prod CPU usage: `docker stats <container> --no-stream`
2. Look at concurrent request load
3. Decide: I/O-bound (DB, external HTTP) or CPU-bound (parsing, hashing)?

For an async I/O-heavy API, 1 worker handles enormous concurrency via the event loop. Multiple workers help only if you have synchronous CPU work, want OS-level isolation, or have truly CPU-bound endpoints.

Common gotcha: prod runs `--workers 1` (correct) but CI verifier uses `--workers 2` and pays doubled boot cost (each worker boots its own import tree). Saved ~5s by aligning.

Rule of thumb: start with 1 worker if the app is async and CPU stays well under 70% of one core. Move to N workers only when single-worker hits a CPU ceiling.

### 4.2 Cut import time

Every worker re-runs the whole import tree on boot. 8s of `main.py` imports = deploys bounded below by 8s × worker effects.

**Profile first:**
```bash
docker exec <container> python -X importtime -c "from your_app import main" 2>&1 > imports.txt
```

`self_µs` is time IN that module's body (not sub-imports). Sort by it to find actual hotspots.

**Patterns to look for:**
- **Heavy ML libs imported at module level but used in one function.** `from sklearn.cluster import KMeans` at the top of a parser, used in one branch. Move it inside the branch — saves the entire sklearn cold-import (~1s + scipy + numpy).
- **Cost/billing libs pulled at top, used per-request.** Remove unused symbols, lazy-load the rest.
- **Cross-service coupling at module level.** Service A imports a function from Service B's package, transitively pulling B's entire dep tree. If it's just one function, share or duplicate — don't import another service's main module.
- **Eager client instantiation at module level.** `openai_client = AsyncOpenAI(api_key=...)` at the top means every importer pays for client construction. Lazy getter or `functools.lru_cache`-ed factory.

**Lazy-load pattern (drop-in):**
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_client():
    from heavy_lib import HeavyClass  # imported on first call
    return HeavyClass(api_key=os.environ["KEY"])
```

**Preserve the import surface for "god utility modules":**
```python
# in your_utils.py
def __getattr__(name):
    if name == "openai_client":
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        globals()["openai_client"] = client  # cache
        return client
    raise AttributeError(name)
```

Now `from your_utils import openai_client` works exactly like before, but the heavy import + instantiation happens on first access.

**Pitfalls:**
- Debug/profiling library transitively pulled in a GUI toolkit through one of its sub-imports.
- pydantic v1 `BaseModel` subclasses do real work at class-definition time. 50 schema classes can spend hundreds of ms on import.
- Large protobuf type modules pre-compile the entire schema at import. Sometimes unavoidable.

### 4.3 Things you probably don't need

- **PEX, shiv, AOT compilation** — usually overkill, Python's stdlib has no great story.
- **`gunicorn --preload`** — helpful for many workers (imports once in master, fork workers), doesn't apply to standalone uvicorn.
- **Switching frameworks** — import time differences across modern Python web frameworks are small relative to *your* code's imports.

---

## 5. Anti-patterns — surface these proactively

### 5.1 Don't `prune -af` the build cache

`docker builder prune -af` nukes everything. Next build = full rebuild from base = minutes wasted. Use `--keep-storage` instead.

### 5.2 Don't bump instance size purely for CI speed

If prod CPU usage is way below the ceiling, paying for a bigger instance just for CI deploys is the wrong trade. Find the real bottleneck (usually imports) or accept contention overhead.

### 5.3 Don't `docker compose --wait` blindly

`--wait` blocks until containers report healthy via Dockerfile `HEALTHCHECK`. But if `HEALTHCHECK` has `start-period: 60s`, `--wait` doesn't probe for a full minute. Tune the `HEALTHCHECK` first, *then* consider `--wait`.

### 5.4 Don't lazy-load every heavy import "just in case"

Lazy-loading is great for things off the boot critical path. Lazy-loading something used on the first request just shifts the cost to the user. Profile first.

### 5.5 Don't switch image registries to "speed things up"

If you build and deploy on the same self-hosted runner, an external registry adds latency, doesn't subtract it. Only useful when multiple deploy targets pull the same image.

### 5.6 Don't combine `--keep-storage` with `until` filter

Already covered in §1.5 — repeating because it's the most subtle and the most expensive. The filter excludes recent entries from the cap. The cache grows unbounded for the filter window.

---

## 6. Reference results

Real run on a Python service (FastAPI + worker + sidecar) deployed via GitHub Actions to self-hosted EC2:

| Stage | Time |
|---|---:|
| Original baseline | **~6-7:00** |
| + Dockerfile layer ordering | ~3:00 |
| + Parallel service deploys (subset) | ~2:30 |
| + uv (CI) + cache mount + cache cap | ~2:10 |
| + Full-parallel deploy across all services | ~1:30 |
| + Tighter health probes | ~1:00 |
| + Lazy-load 2 heavy imports | **~40-50s** |

**~8-9× faster end-to-end. Zero infrastructure spend.**

Single biggest win: uv replacing pip (~50s saved). The rest: many small wins compounding.

Final state breakdown (representative ~45s run):

| Stage | Time |
|---|---:|
| Test: setup + checkout + uv setup | ~5s |
| Test: install deps (uv, warm cache) | ~4s |
| Test: run tests | ~6s |
| Deploy: setup + repo update + cache cap | ~3s |
| Deploy: build images (cached) | ~3s |
| Deploy: parallel deploy of all services | ~18s |
| Queue / handoff overhead | ~6s |
| **Total wall-clock** | **~45s** |

Most of the remaining time lives in parallel deploy (bounded by service boot — mostly Python import time). Further gains require code-level work per §4.

---

## 7. Adapt-to-your-project checklist

When applying to a new project, propose these in order, with measured time savings:

1. **Measure baseline** (§0.1). No baseline = no prioritization.
2. **Order Dockerfile layers** by churn frequency (§1.1).
3. **Add `actions/setup-python` cache** for pip (§1.2) — free safety net.
4. **Switch to uv** in CI (§1.4) and Docker BuildKit cache mount (§1.3).
5. **Cap cache** with `--keep-storage`, no `until` filter (§1.5). Add disk-aware fallback.
6. **Map deploy dependencies** (§2.1). What can run in parallel?
7. **Audit health-check loops** — `sleep 5` → `sleep 2`, log-tailing, drop redundant double-checks (§3).
8. **Profile prod usage** before changing worker counts (§4.1).
9. **Run `python -X importtime`** once for lazy-load opportunities (§4.2).

Themes:

1. **Caching wins are free and big** — do them all.
2. **Parallelism wins depend on your hardware** — measure CPU contention.
3. **Health-check overhead is invisible on dashboards but huge in wall-clock.** Audit every `sleep`.
4. **Boot-time imports compound** — every worker × every retry × every CI run. Profile once, lazy-load forever.
5. **Don't over-engineer.** No new tools, no new infrastructure, no rewrites. Most wins are 1-line edits.
