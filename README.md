# ByteQuest

ByteQuest is a classroom coding game. Teachers and students create separate email/password accounts. Teachers upload a lecture PDF, choose a coding language, review a topic-based quiz and coding challenge, and publish it for students. The Flask backend stores accounts, quests, and scores in SQLite.

## Run locally

1. Install Python 3.10 or newer and Docker Desktop. Start Docker Desktop before running a coding challenge.
2. Open a terminal in this folder and install the Python dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Start the website:

   ```powershell
   python app.py
   ```

4. Visit <http://127.0.0.1:5000>.

Do not open `index.html` directly from File Explorer. Quest generation needs the Flask server, so use the URL above.

Before running student code, pull the sandbox images for the languages you plan to teach:

```powershell
docker pull python:3.13-alpine
docker pull node:22-alpine
docker pull eclipse-temurin:21-jdk-alpine
docker pull gcc:14
docker pull mcr.microsoft.com/dotnet/sdk:8.0
docker pull golang:1.24-alpine
docker pull ruby:3.4-alpine
```

C and C++ share the `gcc:14` image. Docker is required at runtime; submitted code is never executed directly on the Flask host. Each run has no network access, a read-only source mount, memory/CPU/process limits, a 20-second wall-clock limit, and an 8 KB output limit. If Docker or the selected image is unavailable, the challenge displays an error instead of falling back to unsafe execution.

Run the backend tests with:

```powershell
python -m unittest -v
```

The first run creates `data/bytequest.sqlite3`. Set `BYTEQUEST_DATABASE` to use a different SQLite database path. The PDF is processed in memory and is not retained after the draft is generated.

## Classroom workflow

- Register or sign in as a **Teacher** to upload a text-based PDF up to 20 MB, choose a language, review the generated quiz and challenge, then publish.
- Register or sign in as a **Student** to play a published quest. The quiz, challenge output, and XP are checked and recorded by the server.
- Supported challenge languages are Python, JavaScript, Java, C, C++, C#, Go, and Ruby. The challenge shows its problem statement, expected output, and the output from the student's run.

Topic matching and quiz generation use built-in lesson templates, not a hosted AI service. Scanned PDFs without selectable text are not supported. Account passwords are stored as one-way hashes and login sessions use HttpOnly cookies. Set `BYTEQUEST_COOKIE_SECURE=true` when serving over HTTPS.

This project is a local classroom prototype. It allows self-registration for either role and does not include teacher invitations, classroom-specific access controls, or production deployment hardening.
