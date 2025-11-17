# 🌸 Immich Job Daemon Add-on

![Icon](icon.png)

Dieses Home Assistant Add-on hilft dir, **Immich Hintergrundjobs sicher zu steuern**, indem es Konflikte zwischen bestimmten Jobs verhindert. Es sorgt dafür, dass **OCR und smartSearch niemals gleichzeitig laufen**, und berücksichtigt dabei Systemressourcen durch einen Delay beim Wechsel.

---

## 🔧 Basierend auf
Dieses Add-on basiert auf dem Projekt [immich-job-daemon](https://github.com/alternativniy/immich-job-daemon), wurde aber für einen speziellen Anwendungsfall angepasst:

✅ OCR wird beim Start pausiert
✅ smartSearch wird beim Start aktiviert
✅ 10 Sekunden Delay beim Wechsel zwischen den Jobs

---

## ⚙️ Konfiguration

- **`IMMICH_URL`**: URL deines Immich-Servers (z. B. `http://192.168.x.x:2283`)
- **`API_KEY`**: Immich API-Key mit den Berechtigungen `job.read` und `job.create`
- **`POLL_INTERVAL`**: Intervall (in Sekunden), in dem der Status der Jobs überprüft wird

> ⚠️ Die Option `MAX_CONCURRENT_JOBS` wird in dieser Version **nicht mehr verwendet**, da alle Jobs normal laufen dürfen.

---

## 🚀 Features


- 🔒 Läuft als nicht privilegierter Benutzer
- 🌐 Konfiguration über Home Assistant
- ✅ Verhindert, dass OCR und smartSearch gleichzeitig aktiv sind
- ⏸ OCR wird beim Start automatisch pausiert
- ▶️ smartSearch wird beim Start aktiviert
- ⏳ 10 Sekunden Delay beim Wechsel zwischen den Jobs, um RAM-Spitzen zu vermeiden
- 🔄 Automatisches Resume:
  - Wenn OCR fertig ist → smartSearch wird wieder aktiviert
  - Wenn smartSearch fertig ist → OCR wird wieder aktiviert

---

## 🔄 Wie funktioniert es?

Der Daemon läuft alle `POLL_INTERVAL` Sekunden und führt folgende Schritte aus:

1. Pausiert **OCR direkt beim Start**, um Konflikte zu vermeiden.
2. Aktiviert **smartSearch direkt beim Start**, damit es sofort loslegt.
3. Prüft den Status der Jobs über die Immich API.
4. Wenn **OCR aktiv ist**, wird **smartSearch pausiert**.
5. Wenn **smartSearch aktiv ist**, wird **OCR pausiert**.
6. Sobald einer der beiden Jobs fertig ist, wird der andere automatisch wieder gestartet – mit einem **10-Sekunden-Delay**.
7. Alle anderen Jobs laufen unbeeinträchtigt weiter.

---

## 🔐 API Key Berechtigungen

Um einen gültigen API-Key zu erstellen:

1. Melde dich in der Immich Weboberfläche an.
2. Gehe zu **Account Settings → API Keys**.
3. Erstelle einen neuen API-Key mit:
   - ✅ `job.read` – zum Auslesen des Job-Status
   - ✅ `job.create` – zum Pausieren/Fortsetzen von Jobs

> Ohne diese Berechtigungen funktioniert das Add-on nicht.

---

## ✅ Voraussetzungen

- Immich-Server muss vom Home Assistant Add-on erreichbar sein.
- API-Key muss die korrekten Berechtigungen haben.
- Empfohlen: `host` Netzwerkmodus für beste Konnektivität.
