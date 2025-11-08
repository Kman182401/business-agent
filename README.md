# Business Agents – Front Desk AI Platform

_Last updated: 7 November 2025_

This repository is the **single source of truth** for everything that lives in `~/Business Agents` on the local machine. It contains the database schema, FastAPI backend, realtime Twilio/OpenAI bridge, local tooling, and operations docs for the restaurant front-desk agent. The repo is meant to mirror the folder exactly—use `scripts/sync_business_agents.sh` to push every change (adds, edits, removals) to the private GitHub repo `github.com/Kman182401/business-agent`.

### Plain-English Snapshot
- Think of this project as a **virtual front desk teammate**. It answers phone calls, checks the restaurant calendar, saves reservations, and can talk through Twilio just like a human host.
- The **database scripts** define how restaurants, hours, blackouts, and reservation slots are stored so double bookings can’t happen.
- The **FastAPI app** is the brain that receives API requests, checks rules, talks to Redis for short-term holds, and writes confirmed reservations into Postgres.
- The **Twilio/OpenAI realtime bridge** streams live audio between callers and OpenAI’s voice model so guests hear a natural assistant.
- The **sync script** is a “publish” button: run it and whatever is currently in `~/Business Agents` shows up in GitHub.
- If someone brand new reads only this section plus §2, they can understand what exists, what it does today, and what’s left to finish.

---

## 1. Repository Scope & Sync Automation
- **What is tracked**: every file under `~/Business Agents` except virtual environments, compiled caches, and secret `.env` files that are intentionally git-ignored.
- **Sync script**: `scripts/sync_business_agents.sh` bootstraps git (if needed), points `origin` at `https://github.com/Kman182401/business-agent.git`, commits the current working tree, and pushes to `main`.
  ```bash
  # From anywhere
  ~/Business\ Agents/scripts/sync_business_agents.sh "Add schedule parser"
  ```
  - First run initialises `.git`, sets the default branch to `main`, and adds the origin remote.
  - Later runs detect whether there are changes; if none, the script exits cleanly without creating empty commits.
  - Override defaults with `REMOTE_URL` or `BRANCH_NAME` env vars if you ever fork or use a different branch.
- **Optional automation**: add `0 * * * * /home/karson/Business\ Agents/scripts/sync_business_agents.sh` to `crontab -e` to publish once an hour. The script is idempotent and safe to run unattended; failures (e.g., missing GitHub auth) simply raise errors so you can fix credentials.

---

## 2. Current State of the Front Desk Agent
### System Capabilities at a Glance
1. **Answering calls** – Twilio sends live audio to `/ws/twilio-stream`, the OpenAI model responds in real time, and callers hear a natural-sounding voice.
2. **Holding slots** – `/api/v1/availability/check` pre-reserves a slot for five minutes using Redis, so the next caller can’t steal it.
3. **Booking reservations** – `/api/v1/reservations/commit` locks the slot inside Postgres, preventing double bookings even with many simultaneous callers.
4. **Enforcing capacity rules** – SQL functions plus advisory locks limit total parties and covers every 15 minutes, honoring holidays/blackouts.
5. **Health monitoring** – `/api/v1/healthz` and `/api/v1/readiness` prove the app, Postgres, and Redis are reachable before calls are routed.
6. **Observability hooks** – Redis keys, Postgres diagnostics, and Alembic migrations enable troubleshooting and future CI/CD automation.

### 2.1 Data & Persistence (Step 1 complete)
- `sql/001_extensions.sql` – enables `pgcrypto`, `btree_gist`, and `pg_stat_statements` for UUIDs, exclusion constraints, and perf diagnostics.
- `sql/010_schema.sql` – defines restaurants, operating hours, blackout windows, per-slot capacity rules, reservations, and an `event_log` table. Includes GiST range indexes plus a `(restaurant_id, slot_id, shard)` uniqueness guard.
- `sql/020_roles.sql` – creates `app_owner` + `app_user` roles with least-privilege grants (fill in passwords via `sql/params/roles.env`, which stays local only).
- `sql/030_commit_reservation.sql` – PL/pgSQL transaction that acquires advisory locks over every 15-minute bucket to prevent double-booking; enforces max covers/parties before inserting the reservation as `confirmed`.
- `sql/040_seed.sql` – idempotent seed for “Demo Bistro” with daily hours and baseline capacity; safe to rerun for local resets.
- `sql/050_diagnostics.sql` – sample overlap queries to debug availability.
- Alembic: `migrations/versions/8ee43ee7e21f_m1_slot_guard.py` replays the same SQL so schema changes can be promoted with `alembic upgrade head`.

### 2.2 Application Layer (Step 2 in progress)
- `backend/app/main.py` wires FastAPI with a lifespan hook that initialises & closes a shared Redis connection.
- `backend/app/core/config.py` centralises environment variables for DB, Redis, Twilio, public URL, OpenAI Realtime model, etc.
- `backend/app/db/session.py` provides an async SQLAlchemy engine + session factory pointed at Postgres 15/16.
- Routers in `backend/app/routers/`:
  - `health.py` exposes `/api/v1/healthz` and `/api/v1/readiness` (checks DB + Redis).
  - `availability.py` returns a 5-minute Redis hold, capacity projections, and alternate slots when a request conflicts.
  - `reservations.py` converts holds into confirmed bookings via the SQL function and handles race conditions + error mapping.
  - `twilio_voice.py` validates Twilio webhook signatures and replies with `<Connect><Stream>` TwiML that points to our websocket bridge.
  - `twilio_realtime.py` is the realtime bridge: streams µ-law audio from Twilio Media Streams to OpenAI Realtime (`gpt-4o-realtime`), handles naive VAD, rate conversion, and returns synthesized speech to the caller.
- Services: `backend/app/services/reservations.py` wraps the `commit_reservation` SQL call and maps return IDs.
- Redis integration: `backend/app/core/redis_client.py` stores a module-level async client used by both routers and tests.

### 2.3 Tooling & Tests
- `docker-compose.yml` spins Postgres 16 with `pg_stat_statements` plus Redis 7 using local ports `5432` and `6379` by default.
- `requirements.frontdesk.txt` pins every Python dependency used by the API and tests.
- `backend/tests/test_reservations.py` contains async pytest coverage for:
  - Reservation commit success, duplicate holds, and slot conflicts
  - Health/readiness probes
  - Availability hold TTL + alternate slots
  - Parallel commit race protection
  - Capacity overflow rollback & restoration
- `alembic.ini` + `migrations/` let you promote schema updates without manual SQL piping.

---

## 3. Directory Overview
| Path | Purpose |
| --- | --- |
| `backend/app` | FastAPI application modules (routers, services, config, Redis, database session).
| `backend/tests` | Async pytest suite hitting the ASGI app via `httpx.ASGITransport`.
| `sql/` | Hand-authored SQL files for extensions, schema, roles, seed data, diagnostics.
| `migrations/` | Alembic environment and first migration replaying the SQL schema + guard.
| `docker-compose.yml` | Local infra for Postgres + Redis.
| `requirements.frontdesk.txt` | Locked dependency versions for reproducible installs.
| `.env`, `.env.local` | Developer-specific runtime secrets (ignored from git; see §4).
| `scripts/sync_business_agents.sh` | GitHub sync automation described earlier.

---

## 4. Configuration & Secrets
Create a `.env` in the repo root (not checked in) with at least:
```
DATABASE_URL=postgresql+asyncpg://app_user:<password>@127.0.0.1:5432/frontdesk
REDIS_URL=redis://127.0.0.1:6379/0
TWILIO_AUTH_TOKEN=<set-when-going-live>
PUBLIC_BASE_URL=https://<ngrok-subdomain>.ngrok-free.dev
OPENAI_API_KEY=sk-...
REALTIME_MODEL=gpt-4o-realtime
```
Additional helpers:
- `ALEMBIC_DATABASE_URL` controls migrations/tests (see `migrations/env.py` and `backend/tests/test_reservations.py`).
- Keep `sql/params/roles.env` locally filled with production-grade passwords before running `psql -f sql/020_roles.sql`.

---

## 5. Local Bring-Up (Dev Loop)
1. **Install prerequisites**: Python 3.12+, Docker Desktop/Engine, Redis CLI (optional), `psql`, `git`, and `ngrok` for public tunnels.
2. **Start databases**:
   ```bash
   docker compose up -d db redis
   ```
3. **Bootstrap schema + roles**:
   ```bash
   export DATABASE_URL=postgresql://app_owner:change-me@localhost:5432/frontdesk
   psql "$DATABASE_URL" -f sql/001_extensions.sql
   psql "$DATABASE_URL" -f sql/010_schema.sql
   psql "$DATABASE_URL" -f sql/020_roles.sql  # uses roles.env for passwords
   psql "$DATABASE_URL" -f sql/030_commit_reservation.sql
   psql "$DATABASE_URL" -f sql/040_seed.sql
   ```
   Or run `alembic upgrade head` after setting `ALEMBIC_DATABASE_URL`.
4. **Install backend deps**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.frontdesk.txt
   ```
5. **Run the API**:
   ```bash
   source .venv/bin/activate
   uvicorn backend.app.main:app --reload --port 8000
   ```
6. **Call endpoints**:
   ```bash
   http POST :8000/api/v1/availability/check ...
   http POST :8000/api/v1/reservations/commit ...
   curl http://127.0.0.1:8000/api/v1/healthz
   ```
7. **Voice tunnel** (ngrok):
   ```bash
   ngrok http 8000
   export PUBLIC_BASE_URL=$(ngrok url https)
   ```
   Plug the HTTPS URL + `/twilio/voice` into the Twilio Voice webhook, then Twilio will stream audio to `/ws/twilio-stream`.

---

## 6. API Surface Reference
| Endpoint | Module | Notes |
| --- | --- | --- |
| `GET /api/v1/healthz` | `backend/app/routers/health.py` | Liveness check, no deps.
| `GET /api/v1/readiness` | same | Validates Postgres (`SELECT 1`) and Redis `.ping()`.
| `POST /api/v1/availability/check` | `availability.py` | Requires timezone-aware `start_ts`; enforces capacity + holds; returns alternates on HTTP 409.
| `POST /api/v1/reservations/commit` | `reservations.py` | Converts holds to confirmed bookings; surfaces 409 for duplicate/overbooked slots.
| `POST /twilio/voice` | `twilio_voice.py` | Validates Twilio signature (unless dev tunnel) and returns TwiML `<Connect><Stream>`.
| `WS /ws/twilio-stream` | `twilio_realtime.py` | Bi-directional µ-law ↔ PCM16k audio bridge between Twilio Media Streams and OpenAI Realtime.

Payload schemas live in `backend/app/routers/schemas.py` and limit party sizes, note lengths, etc.

---

## 7. Testing & Quality Gates
- **Unit/integration tests**: `source .venv/bin/activate && pytest` (requires Postgres + Redis running and `ALEMBIC_DATABASE_URL` set so fixtures can seed data).
- **Idempotent seeds**: re-run `sql/040_seed.sql` anytime to reset Demo Bistro.
- **Manual verification**: `sql/050_diagnostics.sql` queries confirm slot overlaps and alternate slot logic right inside `psql`.
- **Redis hygiene**: tests explicitly delete hold keys so they can be rerun rapidly; mimic this in manual testing when reusing slots.

---

## 8. Outstanding Work Before Production
1. **Realtime conversation polish**
   - Persist conversational state (caller name/slot) instead of stateless VAD-driven responses.
   - Add OpenAI response templates for edge cases (no availability, restaurant closed, etc.).
2. **Twilio hardening**
   - Enforce signature validation even on ngrok (introduce allow-list for dev URLs).
   - Add call status callbacks + failover number for human takeover.
3. **Operational tooling**
   - Build `/api/v1/reservations/{id}` CRUD + cancellation endpoints.
   - Emit structured logs/metrics (OpenTelemetry or Prometheus) for slot holds, reservation throughput, and Twilio call IDs.
   - Add Alertmanager hooks when Redis lag spikes or commit latency exceeds SLA.
4. **Data enrichment**
   - Model table-level seating + exclusion constraints for per-table limits.
   - Add blackout/holiday editor plus UI (even CLI) to update capacity windows without SQL.
5. **Testing gaps**
   - Load tests for overlapping holds (simulate 50+ concurrent callers).
   - Contract tests for Twilio webhook payloads and OpenAI realtime responses.
6. **Deployment**
   - Containerise the API + bridge, bake migrations into entrypoint, and deploy onto Fly.io/ECS/Kubernetes.
   - Add GitHub Actions pipeline that runs lint/tests + pushes Docker images before `sync_business_agents.sh` pushes code.

---

## 9. Troubleshooting
- **`redis.exceptions.ConnectionError`** – ensure `docker compose up redis` and check `REDIS_URL`.
- **`HTTP 409 Slot temporarily held`** – either wait 5 minutes (hold TTL) or manually delete the key with `redis-cli DEL <key>` while testing.
- **`Twilio 403 Invalid signature`** – confirm `TWILIO_AUTH_TOKEN` matches the console and `PUBLIC_BASE_URL` matches the webhook URL exactly (no trailing slash mismatch).
- **`git push` fails inside the sync script** – run `gh auth login` or configure a personal access token; rerun the script after authentication.

---

## 10. Keeping GitHub in Sync
1. Make any code/doc changes inside `~/Business Agents`.
2. Run `scripts/sync_business_agents.sh "Meaningful commit message"`.
3. Verify `git status` (should be clean) and confirm GitHub shows the update.
4. Repeat often; consider a cron job or macOS Automator/Windows Task Scheduler to call the script hourly.

That’s the full picture of the front desk agent so far. Use this README as the living journal for architecture decisions, checklists, and future milestones.
