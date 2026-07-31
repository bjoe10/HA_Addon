# 🌸 Immich Job Daemon Add-on

![Icon](icon.png)

This Home Assistant add-on helps you **manage Immich's heavy, RAM-hungry background jobs** via the Immich API. It makes sure that only a defined number of ML jobs run at the same time, so they never pile up and exhaust memory on low-powered systems (e.g. Raspberry Pi). Lightweight jobs (thumbnails, metadata, sidecar, etc.) are left completely alone and run on Immich's own schedule.

---

## 🔧 Based on

This add-on is based on the original project [immich-job-daemon](https://github.com/alternativniy/immich-job-daemon), a lightweight Alpine-based daemon that manages Immich job queues by priority — extended here to only touch the heavy ML jobs and to be resilient to being stopped/restarted.

---

## ⚙️ Configuration

- **`IMMICH_URL`**: URL of your Immich server (e.g., `http://192.168.x.x:2283`)
- **`API_KEY`**: Immich API key with `job.read` and `job.create` permissions
- **`MAX_CONCURRENT_JOBS`**: Maximum number of heavy jobs allowed to run at the same time
- **`POLL_INTERVAL`**: Interval (in seconds) for checking job status

If Home Assistant Supervisor doesn't pass these options through as environment variables on your setup, the daemon automatically falls back to reading them directly from `/data/options.json` — no extra configuration needed.

---

## 🚀 Features

- 🐧 Minimal Alpine-based (`bash:5.1`) image
- 🎯 Only manages the heavy ML jobs — thumbnails, metadata, sidecar, library scans etc. run unmanaged, as Immich intends
- 🔄 Automatic job priority management among the managed jobs
- ⚙️ Configurable number of concurrent heavy jobs
- 🛑 Graceful shutdown: always resumes all managed jobs before exiting, so stopping/restarting the add-on never leaves a job permanently paused
- 🔒 Runs as non-privileged user
- 🌐 Configuration via Home Assistant options (with `/data/options.json` fallback)

---

## 🎯 Managed (heavy) Jobs

Only the following RAM/CPU-intensive jobs are actively paused/resumed by the daemon, in this priority order:

1. `smartSearch` (CLIP embeddings)
2. `facialRecognition`
3. `faceDetection`
4. `duplicateDetection`
5. `videoConversion` (transcoding)
6. `ocr`

**Everything else** — `sidecar`, `metadataExtraction`, `thumbnailGeneration`, `storageTemplateMigration`, `library`, `migration`, `backgroundTask`, `notifications`, `workflow`, `backupDatabase`, `integrityCheck`, `editor`, and any future job types Immich adds — is never touched by the daemon and simply runs whenever Immich schedules it.

---

## 🔄 How It Works

The daemon runs every N seconds (configurable via `POLL_INTERVAL`), and only considers the managed heavy-job list above:

1. Fetches all jobs from the Immich API
2. Checks whether any managed job is currently actively running (active > 0)
3. If there are active jobs – continues their execution until completion (does not interrupt)
4. If none are active – finds the first N jobs from the priority list (where N = `MAX_CONCURRENT_JOBS`) that have tasks queued
5. Resumes the selected jobs
6. Pauses all other managed jobs

This keeps memory usage predictable by processing heavy ML jobs sequentially or in small batches according to priority, **without interrupting already-running jobs**, and without ever interfering with Immich's own handling of lightweight jobs.

On shutdown (stop/restart of the add-on), the daemon resumes every managed job before exiting, so it never leaves the queue stuck in a paused state.

---

## 🔐 API Key Permissions

To generate a valid API key:

1. Log in to Immich web interface
2. Go to **Account Settings → API Keys**
3. Create a new API key with required permissions:
   - ✅ `job.read` – to read job status
   - ✅ `job.create` – to manage jobs (pause/resume)

> ⚠️ The daemon will not work without these permissions.

---

## ✅ Requirements

- Immich server must be reachable from the Home Assistant add-on container
- API key must have the correct permissions
- Recommended: Use `host` network mode for best connectivity
