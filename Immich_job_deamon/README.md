# 🌸 Immich Job Daemon Add-on

![Icon](icon.png)

This Home Assistant add-on helps you **manage Immich background jobs efficiently** via the Immich API.  
It ensures that only a defined number of jobs run concurrently, saving resources on low-powered systems.

---

## ⚙️ Configuration

- **`IMMICH_URL`**: URL of your Immich server (e.g., `http://192.168.x.x:2283`)
- **`API_KEY`**: Immich API key with `job.read` and `job.create` permissions
- **`MAX_CONCURRENT_JOBS`**: Maximum number of jobs allowed to run at the same time
- **`POLL_INTERVAL`**: Interval (in seconds) for checking job status

---

## ✅ Requirements

- Immich server must be reachable from the Home Assistant add-on container
- API key must have the correct permissions
- Recommended: Use `host` network mode for best connectivity

