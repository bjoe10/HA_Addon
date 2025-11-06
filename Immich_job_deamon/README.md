
# 🌸 Immich Job Daemon Add-on

![Icon](icon.png)

This Home Assistant add-on helps you **manage Immich background jobs efficiently** via the Immich API. It ensures that only a defined number of jobs run concurrently, saving resources on low-powered systems.

---

## 🔧 Based on
This add-on is based on the original project [immich-job-daemon](https://github.com/alternativniy/immich-job-daemon), a lightweight Alpine-based daemon that manages Immich job queues by priority.

---

## ⚙️ Configuration

- **`IMMICH_URL`**: URL of your Immich server (e.g., `http://192.168.x.x:2283`)
- **`API_KEY`**: Immich API key with `job.read` and `job.create` permissions
- **`MAX_CONCURRENT_JOBS`**: Maximum number of jobs allowed to run at the same time
- **`POLL_INTERVAL`**: Interval (in seconds) for checking job status

---

## 🚀 Features

- 🐧 Based on Alpine Linux (minimal image size)
- 🔄 Automatic job priority management
- ⚙️ Configurable number of concurrent jobs
- 🔒 Runs as non-privileged user
- 🌐 Configuration via Home Assistant options

---

## 📊 Job Priority
Jobs are processed in the following priority order:

1. sidecar
2. metadataExtraction
3. storageTemplateMigration
4. thumbnailGeneration
5. smartSearch
6. duplicateDetection
7. faceDetection
8. facialRecognition
9. videoConversion
10. other jobs

---

## 🔄 How It Works

The daemon runs every N seconds (configurable via `POLL_INTERVAL`):

1. Fetches all jobs from Immich API
2. Checks for actively running jobs (active > 0)
3. If there are active jobs – continues their execution until completion (does not interrupt)
4. If all jobs are paused – finds the first N jobs from the priority list (where N = `MAX_CONCURRENT_JOBS`) that have tasks in queue
5. Resumes selected jobs
6. Pauses all other managed jobs

This allows efficient server resource management by processing jobs sequentially or in parallel according to priority, **without interrupting already running jobs**.

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

