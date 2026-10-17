from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, make_response, request, send_from_directory
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 150
MAX_CODE_CHARS = 10_000
MAX_OUTPUT_BYTES = 8_192
SUPPORTED_LANGUAGES = {
    "python": {"name": "Python", "image": "python:3.13-alpine", "file": "main.py", "command": ["python", "-I", "/workspace/main.py"]},
    "javascript": {"name": "JavaScript", "image": "node:22-alpine", "file": "main.js", "command": ["node", "/workspace/main.js"]},
    "java": {"name": "Java", "image": "eclipse-temurin:21-jdk-alpine", "file": "Main.java", "command": ["sh", "-c", "cd /tmp && javac /workspace/Main.java && java -cp /tmp Main"]},
    "c": {"name": "C", "image": "gcc:14", "file": "main.c", "command": ["sh", "-c", "gcc /workspace/main.c -o /tmp/main && /tmp/main"]},
    "cpp": {"name": "C++", "image": "gcc:14", "file": "main.cpp", "command": ["sh", "-c", "g++ /workspace/main.cpp -o /tmp/main && /tmp/main"]},
    "csharp": {"name": "C#", "image": "mcr.microsoft.com/dotnet/sdk:8.0", "file": "Program.cs", "command": ["sh", "-c", "mkdir -p /tmp/app && cp /workspace/Program.cs /tmp/app/Program.cs && printf '%s' '<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>' > /tmp/app/app.csproj && cd /tmp/app && dotnet restore --ignore-failed-sources app.csproj >/dev/null && dotnet build --no-restore --verbosity:quiet app.csproj >/dev/null && dotnet bin/Debug/net8.0/app.dll"]},
    "go": {"name": "Go", "image": "golang:1.24-alpine", "file": "main.go", "command": ["sh", "-c", "cd /tmp && GO111MODULE=off GOCACHE=/tmp/go-cache go run /workspace/main.go"]},
    "ruby": {"name": "Ruby", "image": "ruby:3.4-alpine", "file": "main.rb", "command": ["ruby", "/workspace/main.rb"]},
}
SESSION_COOKIE = "bytequest_session"
SESSION_LIFETIME_SECONDS = 7 * 24 * 60 * 60

TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("while loops", re.compile(r"\b(while\s+loops?|while-loops?)\b", re.I)),
    ("for loops", re.compile(r"\b(for\s+loops?|for-loops?|iteration|iterable)\b|\brange\s*\(", re.I)),
    ("loops", re.compile(r"\b(loops?|repetition|repeat)\b", re.I)),
    ("functions", re.compile(r"\b(functions?|def\s+\w+|parameters?|return\s+value)\b", re.I)),
    ("lists", re.compile(r"\b(lists?|arrays?|append)\b", re.I)),
    ("conditionals", re.compile(r"\b(conditionals?|if\s+statements?|if-else|elif|boolean)\b", re.I)),
    ("variables", re.compile(r"\b(variables?|assignment|data\s+types?|datatype)\b", re.I)),
    ("strings", re.compile(r"\b(strings?|concatenation|substring)\b", re.I)),
)


def _question(
    prompt: str,
    options: list[str],
    answer: int,
    explanation: str,
) -> dict[str, Any]:
    return {
        "question": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def build_questions(topic: str, language: str = "python") -> list[dict[str, Any]]:
    """Return a reviewed starter quiz for the detected programming topic."""
    language_name = SUPPORTED_LANGUAGES.get(language, SUPPORTED_LANGUAGES["python"])["name"]
    if "loop" in topic:
        loop_examples = {
            "python": "for i in range(4):",
            "javascript": "for (let i = 0; i < 4; i++)",
            "java": "for (int i = 0; i < 4; i++)",
            "c": "for (int i = 0; i < 4; i++)",
            "cpp": "for (int i = 0; i < 4; i++)",
            "csharp": "for (int i = 0; i < 4; i++)",
            "go": "for i := 0; i < 4; i++",
            "ruby": "4.times do |i|",
        }
        example = loop_examples.get(language, loop_examples["python"])
        return [
            _question(
                "What does a for loop help you do?",
                ["Repeat a block of code", "Rename a variable", "Create a new data type", "Stop a program"],
                0,
                "A for loop runs a block once for each item in a sequence.",
            ),
            _question(
                f"How many times does <code>{example}</code> run?",
                ["3 times", "4 times", "5 times", "It runs forever"],
                1,
                "The loop repeats four times.",
            ),
            _question(
                "Which keyword repeats code while a condition is true?",
                ["repeat", "again", "while", "until"],
                2,
                "A while loop continues while its condition remains true.",
            ),
            _question(
                "What is a common reason to use a loop?",
                ["Repeat work for several values", "Rename a function", "Create a file", "End every program"],
                0,
                "Loops repeat a block of instructions.",
            ),
        ]
    if topic == "functions":
        return [
            _question("What is a function or method useful for?", ["Reusing a named block of instructions", "Storing only one character", "Stopping the computer", "Changing a file type"], 0, "Functions and methods package reusable instructions."),
            _question("What is a parameter?", ["An input a function can receive", "A loop that never ends", "A comment", "A file name"], 0, "Parameters let a function receive values when it is called."),
            _question("What does a return value provide?", ["A result from a function", "A new source file", "A loop condition", "A comment"], 0, "A return value sends a result back to the caller."),
            _question("How do you call a function named greet?", ["call greet", "greet()", "def greet", "run:greet"], 1, "Use the function name followed by parentheses: greet()."),
        ]
    if topic == "lists":
        return [
            _question("What is a list or collection used for?", ["Keeping several values together", "Repeating a program forever", "Naming a function", "Printing a file"], 0, "Collections group related values."),
            _question("What is the index of the first item in a typical array or list?", ["0", "1", "-1", "It has no index"], 0, "Most common arrays and lists use zero-based indexing."),
            _question("What should you use to add an item to a collection?", ["A collection's add operation", "A comment", "A return type", "A loop condition"], 0, "Collections provide an operation for adding values."),
            _question("How many items are in a collection containing 4, 8, and 9?", ["2", "3", "4", "9"], 1, "There are three values in the collection."),
        ]
    if topic == "conditionals":
        return [
            _question(f"Which keyword begins a conditional in {language_name}?", ["when", "if", "check", "case"], 1, "An if statement runs its block when a condition is true."),
            _question("What does else do?", ["Repeats a block", "Runs when the if condition is false", "Defines a function", "Ends the program"], 1, "else provides the alternative when the if condition is false."),
            _question("Which operator checks whether two values are equal?", ["=", "==", "!=", "=>"], 1, "== compares values; a single = assigns a value."),
            _question("What type of value does a comparison produce?", ["String", "List", "Boolean", "Function"], 2, "A comparison evaluates to True or False, a Boolean value."),
        ]
    if topic == "variables":
        return [
            _question("What does assigning a value to a variable do?", ["Stores a value under a name", "Repeats a block", "Defines a class", "Prints a file"], 0, "Assignment associates a value with a variable name."),
            _question("Which is a valid variable name in the supported languages?", ["2score", "student-name", "student_score", "class"], 2, "Variable names cannot start with a digit or contain a hyphen; class is reserved."),
            _question("How would you describe the value 3.5?", ["A decimal number", "A string", "A boolean", "A function"], 0, "3.5 is a number with a fractional part."),
            _question("What does a variable do?", ["Stores a value under a name", "Prints a file", "Repeats code", "Creates a folder"], 0, "A variable is a name associated with a value."),
        ]
    if topic == "strings":
        return [
            _question("Which value is a string?", ["42", "True", '"hello"', "[1, 2]"], 2, "Text in quotes, such as 'hello', is a string."),
            _question("How many characters are in the string <code>\"code\"</code>?", ["3", "4", "5", "code"], 1, "The string contains four characters."),
            _question("Which operator joins two strings?", ["+", "*", "//", "%"], 0, "The + operator concatenates strings."),
            _question("What is the result of <code>'py' + 'thon'</code>?", ["py thon", "python", "py+thon", "An error"], 1, "Adding strings joins them into 'python'."),
        ]
    return [
        _question(f"What is a good way to understand a new {language_name} concept?", ["Read an example line by line", "Skip all examples", "Change every value at once", "Close the editor"], 0, "Following an example line by line makes each step easier to understand."),
        _question("What should you do when code behaves unexpectedly?", ["Debug it step by step", "Ignore the output", "Add random code", "Delete the project"], 0, "Debugging step by step helps locate the cause of a problem."),
        _question("Why are descriptive variable names useful?", ["They explain what data represents", "They change the output", "They replace Python", "They prevent every error"], 0, "Descriptive names make code easier to understand."),
        _question("How can you check whether a small code change works?", ["Run the code and inspect its result", "Assume it worked", "Remove the tests", "Rename the folder"], 0, "Running the program lets you check its actual behavior."),
    ]


def make_quest(text: str, filename: str, language: str = "python") -> dict[str, Any]:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("Choose one of the supported programming languages.")
    matches = [(len(pattern.findall(text)), topic) for topic, pattern in TOPIC_PATTERNS]
    match_count, topic = max(matches, key=lambda match: match[0], default=(0, "Python coding"))
    if not match_count:
        topic = "Python coding"

    loop_topic = "loop" in topic
    title = "Loop-de-loop" if loop_topic else f"{topic.title()} quest"
    focus = "the key ideas" if topic == "Python coding" else topic
    challenge, expected_output = {
        "for loops": ("Print the numbers 1 through 5, one number per line.", "1\n2\n3\n4\n5"),
        "while loops": ("Print the numbers 1 through 5, one number per line.", "1\n2\n3\n4\n5"),
        "loops": ("Print the numbers 1 through 5, one number per line.", "1\n2\n3\n4\n5"),
        "functions": ('Define and call a function that prints "Hello, ByteQuest!".', "Hello, ByteQuest!"),
        "variables": ('Store "ByteQuest" in a variable and print it.', "ByteQuest"),
        "strings": ('Join the strings "Byte" and "Quest", then print the result.', "ByteQuest"),
        "conditionals": ('If score is at least 10, print "ByteQuest".', "ByteQuest"),
        "lists": ('Create a collection with "ByteQuest" as its first item and print that item.', "ByteQuest"),
    }.get(topic, ('Print the text "ByteQuest".', "ByteQuest"))
    return {
        "title": title,
        "topic": topic,
        "description": f"Turn {focus} into your next coding superpower",
        "challenge": challenge,
        "expected_output": expected_output,
        "language": language,
        "file_name": filename,
        "questions": build_questions(topic, language),
    }


def extract_pdf_text(file_storage: Any) -> tuple[str, str]:
    filename = secure_filename(file_storage.filename or "")
    if not filename or not filename.lower().endswith(".pdf"):
        raise ValueError("Choose a PDF lecture file.")

    data = file_storage.stream.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("That PDF is too large. Choose a file smaller than 20 MB.")
    if not data:
        raise ValueError("The selected PDF is empty.")

    try:
        from io import BytesIO

        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected. Upload an unlocked copy.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDFs can have at most {MAX_PDF_PAGES} pages.")
        text = " ".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as error:
        raise ValueError("The file is not a valid, readable PDF.") from error
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("The PDF could not be read.") from error

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("No selectable text was found. This may be a scanned PDF; upload a text-based PDF.")
    if len(text) > 1_000_000:
        text = text[:1_000_000]
    return text, filename


def validate_code(topic: str, source: str) -> tuple[bool, str]:
    if not source.strip():
        return False, "Write a little code first, then check your solution."
    if len(source) > MAX_CODE_CHARS:
        return False, "Your answer is too long. Keep it under 10,000 characters."
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as error:
        return False, f"Python syntax error on line {error.lineno or 1}. Check your indentation and punctuation."
    if not tree.body:
        return False, "Add a Python statement to your answer."

    nodes = list(ast.walk(tree))
    calls = [node for node in nodes if isinstance(node, ast.Call)]
    called_names = {node.func.id for node in calls if isinstance(node.func, ast.Name)}
    valid = False
    tip = "Add a short Python example that demonstrates the lesson topic."

    if "loop" in topic:
        valid = any(isinstance(node, (ast.For, ast.While)) for node in nodes) and "print" in called_names
        tip = "Try adding a for or while loop that calls print()."
    elif topic == "functions":
        valid = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in nodes)
        tip = "Define a function with def and give it a short body."
    elif topic == "conditionals":
        valid = any(isinstance(node, ast.If) for node in nodes)
        tip = "Add an if statement (optionally with else) to your example."
    elif topic == "lists":
        valid = any(isinstance(node, (ast.List, ast.ListComp)) for node in nodes) or any(
            isinstance(node.func, ast.Attribute) and node.func.attr == "append" for node in calls
        )
        tip = "Create a list with square brackets or add an item with append()."
    elif topic == "variables":
        valid = any(isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) for node in nodes)
        tip = "Assign a value to a variable using =."
    elif topic == "strings":
        valid = any(
            isinstance(node, ast.Constant) and isinstance(node.value, str)
            for node in nodes
        )
        tip = "Use a quoted string in your Python example."
    else:
        valid = True

    if not valid:
        return False, tip
    return True, "Great work! Your code has valid Python syntax and demonstrates the lesson topic."


def run_code_in_sandbox(language: str, source: str) -> dict[str, Any]:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("That programming language is not supported.")
    if not source.strip():
        raise ValueError("Write a little code first, then run your solution.")
    if len(source) > MAX_CODE_CHARS:
        raise ValueError("Your answer is too long. Keep it under 10,000 characters.")
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker Desktop is required to run code safely. Install and start Docker Desktop, then try again.")

    container_name = f"bytequest-{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="bytequest-") as work_dir:
        source_path = Path(work_dir) / SUPPORTED_LANGUAGES[language]["file"]
        source_path.write_text(source, encoding="utf-8")
        mount_path = str(Path(work_dir).resolve())
        image = SUPPORTED_LANGUAGES[language]["image"]
        command = [
            docker, "run", "--rm", "--pull=never", "--name", container_name,
            "--network", "none", "--memory", "512m", "--cpus", "0.5",
            "--pids-limit", "32", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=32m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", "--env", "HOME=/tmp",
            "--entrypoint", "/bin/sh",
            "--mount", f"type=bind,source={mount_path},target=/workspace,readonly",
            image, "-c", shlex.join(SUPPORTED_LANGUAGES[language]["command"]),
        ]
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except OSError as exception:
            raise RuntimeError("Docker could not start the code sandbox.") from exception

        output = bytearray()
        output_limit_reached = threading.Event()

        def collect_output() -> None:
            assert process.stdout is not None
            while chunk := process.stdout.read(1024):
                available = MAX_OUTPUT_BYTES - len(output)
                output.extend(chunk[:available])
                if len(chunk) > available:
                    output_limit_reached.set()
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    return

        reader = threading.Thread(target=collect_output, daemon=True)
        reader.start()
        timed_out = False
        try:
            return_code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = -1
            process.kill()
            process.wait()
        if output_limit_reached.is_set() or timed_out:
            try:
                cleanup = subprocess.run(
                    [docker, "rm", "--force", container_name],
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
            except OSError as exception:
                raise RuntimeError("The code sandbox stopped responding and Docker could not stop its container.") from exception
            except subprocess.TimeoutExpired as exception:
                raise RuntimeError("Docker could not stop the code sandbox within 3 seconds.") from exception
            cleanup_message = (cleanup.stdout + cleanup.stderr).decode("utf-8", errors="replace").lower()
            if cleanup.returncode and "no such container" not in cleanup_message:
                raise RuntimeError("Docker could not stop the code sandbox: " + cleanup_message.strip())
        reader.join(timeout=2)
        if timed_out:
            raise RuntimeError("Your code took too long. Keep it under 20 seconds and try again.")
        result_output = output.decode("utf-8", errors="replace")
        if output_limit_reached.is_set():
            result_output += "\n[Output truncated at 8 KB]"
        lowered_output = result_output.lower()
        if "unable to find image" in lowered_output or "pull access denied" in lowered_output or "no such image" in lowered_output:
            raise RuntimeError(f"The {SUPPORTED_LANGUAGES[language]['name']} sandbox image is missing. Follow the Docker setup instructions in README.md.")
        if "cannot connect to the docker daemon" in lowered_output or "error during connect" in lowered_output:
            raise RuntimeError("Docker Desktop is installed but not running. Start it and try again.")
        return {"output": result_output, "exit_code": return_code}


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE=os.environ.get("BYTEQUEST_DATABASE", str(BASE_DIR / "data" / "bytequest.sqlite3")),
        MAX_CONTENT_LENGTH=MAX_PDF_BYTES + 1024 * 1024,
        SESSION_COOKIE_SECURE=os.environ.get("BYTEQUEST_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)

    def connect_db() -> sqlite3.Connection:
        connection = sqlite3.connect(app.config["DATABASE"], timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize_database() -> None:
        database_path = Path(app.config["DATABASE"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect_db()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS students (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
                    streak INTEGER NOT NULL DEFAULT 0 CHECK (streak >= 0),
                    last_completed_date TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quests (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    description TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    expected_output TEXT NOT NULL DEFAULT 'ByteQuest',
                    language TEXT NOT NULL DEFAULT 'python',
                    file_name TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL REFERENCES students(id),
                    quest_id TEXT NOT NULL REFERENCES quests(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    challenge_passed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (student_id, quest_id, id)
                );
                CREATE TABLE IF NOT EXISTS attempt_answers (
                    attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    question_index INTEGER NOT NULL,
                    answer_index INTEGER NOT NULL,
                    is_correct INTEGER NOT NULL,
                    PRIMARY KEY (attempt_id, question_index)
                );
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL REFERENCES students(id),
                    quest_id TEXT NOT NULL REFERENCES quests(id),
                    xp_earned INTEGER NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS activities_by_student ON activities(student_id, completed_at DESC);
                CREATE INDEX IF NOT EXISTS attempts_by_student ON attempts(student_id, created_at DESC);
                """
            )
            quest_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(quests)")
            }
            if "expected_output" not in quest_columns:
                connection.execute(
                    "ALTER TABLE quests ADD COLUMN expected_output TEXT NOT NULL DEFAULT 'ByteQuest'"
                )
            if "language" not in quest_columns:
                connection.execute(
                    "ALTER TABLE quests ADD COLUMN language TEXT NOT NULL DEFAULT 'python'"
                )

    def error(message: str, status: int):
        return jsonify({"error": message}), status

    def authenticated_user(connection: sqlite3.Connection):
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        return connection.execute(
            """
            SELECT users.id, users.email, users.name, users.role
            FROM auth_sessions JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ? AND auth_sessions.expires_at > ?
            """,
            (hashlib.sha256(token.encode("utf-8")).hexdigest(), int(datetime.now(timezone.utc).timestamp())),
        ).fetchone()

    def require_role(*roles: str):
        def decorator(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                with closing(connect_db()) as connection:
                    user = authenticated_user(connection)
                if user is None:
                    return error("Sign in to continue.", 401)
                if roles and user["role"] not in roles:
                    return error("This account does not have permission to do that.", 403)
                g.user_id = user["id"]
                g.user_role = user["role"]
                return function(*args, **kwargs)

            return wrapped

        return decorator

    def public_question(question: dict[str, Any]) -> dict[str, Any]:
        return {"question": question["question"], "options": question["options"]}

    def quest_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "topic": row["topic"],
            "description": row["description"],
            "challenge": row["challenge"],
            "expected_output": row["expected_output"],
            "language": row["language"],
            "file_name": row["file_name"],
            "question_count": len(json.loads(row["questions_json"])),
            "published_at": row["published_at"],
        }

    def current_student(connection: sqlite3.Connection):
        return connection.execute(
            "SELECT * FROM students WHERE id = ?", (g.user_id,)
        ).fetchone()

    def set_session_cookie(response, token: str):
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_LIFETIME_SECONDS,
            httponly=True,
            secure=app.config["SESSION_COOKIE_SECURE"],
            samesite="Lax",
            path="/",
        )
        return response

    def latest_quest(connection: sqlite3.Connection):
        return connection.execute(
            "SELECT * FROM quests WHERE status = 'published' ORDER BY published_at DESC, rowid DESC LIMIT 1"
        ).fetchone()

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        if filename not in {"backend.js", "styles.css", "favicon.ico"}:
            return error("File not found.", 404)
        path = BASE_DIR / filename
        if not path.is_file():
            return error("File not found.", 404)
        return send_from_directory(BASE_DIR, filename)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/api/auth/register")
    def register():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return error("Provide account details as a JSON object.", 400)
        email = body.get("email")
        password = body.get("password")
        role = body.get("role")
        name = body.get("name")
        if not isinstance(email, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
            return error("Enter a valid email address.", 400)
        if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
            return error("Use a password between 8 and 128 characters.", 400)
        if not isinstance(role, str) or role not in {"teacher", "student"}:
            return error("Choose Teacher or Student for this account.", 400)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            return error("Enter a name between 1 and 40 characters.", 400)

        user_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = int(datetime.now(timezone.utc).timestamp())
        with closing(connect_db()) as connection, connection:
            connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            try:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, role, name) VALUES (?, ?, ?, ?, ?)",
                    (user_id, email.strip().casefold(), generate_password_hash(password), role, name.strip()),
                )
            except sqlite3.IntegrityError:
                return error("An account with that email already exists.", 409)
            if role == "student":
                connection.execute(
                    "INSERT INTO students (id, name) VALUES (?, ?)", (user_id, name.strip())
                )
            connection.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), user_id, now + SESSION_LIFETIME_SECONDS),
            )
        response = make_response(jsonify({"user": {"id": user_id, "name": name.strip(), "email": email.strip().casefold(), "role": role}}), 201)
        return set_session_cookie(response, token)

    @app.post("/api/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return error("Provide your sign-in details as a JSON object.", 400)
        email = body.get("email")
        password = body.get("password")
        role = body.get("role")
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > 128 or not isinstance(role, str) or role not in {"teacher", "student"}:
            return error("Enter your email, password, and account type.", 400)
        with closing(connect_db()) as connection, connection:
            user = connection.execute(
                "SELECT id, email, name, role, password_hash FROM users WHERE email = ?",
                (email.strip().casefold(),),
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password) or user["role"] != role:
                return error("Email, password, or account type is incorrect.", 401)
            token = secrets.token_urlsafe(32)
            now = int(datetime.now(timezone.utc).timestamp())
            connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), user["id"], now + SESSION_LIFETIME_SECONDS),
            )
        response = make_response(jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}))
        return set_session_cookie(response, token)

    @app.get("/api/auth/me")
    def auth_me():
        with closing(connect_db()) as connection:
            user = authenticated_user(connection)
            if user is None:
                return error("Sign in to continue.", 401)
            return jsonify({"user": dict(user)})

    @app.post("/api/auth/logout")
    def logout():
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            with closing(connect_db()) as connection, connection:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                )
        response = make_response(jsonify({"ok": True}))
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="Lax")
        return response

    @app.get("/api/bootstrap")
    @require_role("teacher", "student")
    def bootstrap():
        with closing(connect_db()) as connection, connection:
            student = current_student(connection)
            quest = latest_quest(connection)
            today = date.today().isoformat()
            completed_today = 0
            if student:
                completed_today = connection.execute(
                    "SELECT COUNT(*) FROM activities WHERE student_id = ? AND date(completed_at) = ?",
                    (student["id"], today),
                ).fetchone()[0]
            leaderboard = connection.execute(
                "SELECT id, name, xp FROM students ORDER BY xp DESC, name COLLATE NOCASE LIMIT 10"
            ).fetchall()
            activities = []
            if student:
                activities = connection.execute(
                    """
                    SELECT activities.xp_earned, activities.completed_at, quests.title, quests.topic
                    FROM activities JOIN quests ON quests.id = activities.quest_id
                    WHERE activities.student_id = ?
                    ORDER BY activities.completed_at DESC, activities.id DESC LIMIT 5
                    """,
                    (student["id"],),
                ).fetchall()
            return jsonify(
                {
                    "student": {
                        "id": student["id"],
                        "name": student["name"],
                        "xp": student["xp"],
                        "streak": student["streak"],
                        "completed_today": completed_today,
                    } if student else None,
                    "quest": quest_summary(quest) if quest else None,
                    "leaderboard": [dict(row) for row in leaderboard],
                    "activities": [dict(row) for row in activities] if student else [],
                }
            )

    @app.put("/api/students/me")
    @require_role("student")
    def rename_student():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            return error("Enter a name between 1 and 40 characters.", 400)
        with closing(connect_db()) as connection, connection:
            student = current_student(connection)
            connection.execute(
                "UPDATE students SET name = ? WHERE id = ?",
                (name.strip(), g.user_id),
            )
            connection.execute(
                "UPDATE users SET name = ? WHERE id = ?",
                (name.strip(), g.user_id),
            )
        return jsonify({"name": name.strip()})

    @app.post("/api/quests/drafts")
    @require_role("teacher")
    def create_draft():
        uploaded_file = request.files.get("pdf")
        if uploaded_file is None:
            return error("Attach a lecture PDF using the 'pdf' field.", 400)
        try:
            text, filename = extract_pdf_text(uploaded_file)
        except ValueError as exception:
            return error(str(exception), 400)
        language = request.form.get("language", "python")
        try:
            quest = make_quest(text, filename, language)
        except ValueError as exception:
            return error(str(exception), 400)
        draft_id = str(uuid.uuid4())
        with closing(connect_db()) as connection, connection:
            connection.execute(
                """
                INSERT INTO quests (id, title, topic, description, challenge, expected_output, language, file_name, questions_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    draft_id,
                    quest["title"],
                    quest["topic"],
                    quest["description"],
                    quest["challenge"],
                    quest["expected_output"],
                    quest["language"],
                    quest["file_name"],
                    json.dumps(quest["questions"]),
                ),
            )
        return jsonify({**quest_summary_from_dict(draft_id, quest), "questions": [public_question(q) for q in quest["questions"]]}), 201

    @app.post("/api/quests/<quest_id>/publish")
    @require_role("teacher")
    def publish_quest(quest_id: str):
        with closing(connect_db()) as connection, connection:
            cursor = connection.execute(
                "UPDATE quests SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'draft'",
                (quest_id,),
            )
            if cursor.rowcount != 1:
                return error("This quest draft no longer exists. Upload the lecture again.", 404)
            quest = connection.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        return jsonify({"quest": quest_summary(quest)})

    @app.get("/api/leaderboard")
    @require_role("teacher", "student")
    def leaderboard():
        with closing(connect_db()) as connection, connection:
            rows = connection.execute(
                "SELECT name, xp FROM students ORDER BY xp DESC, name COLLATE NOCASE LIMIT 10"
            ).fetchall()
        return jsonify({"players": [dict(row) for row in rows]})

    @app.post("/api/quests/<quest_id>/attempts")
    @require_role("student")
    def start_attempt(quest_id: str):
        with closing(connect_db()) as connection, connection:
            quest = connection.execute(
                "SELECT * FROM quests WHERE id = ? AND status = 'published'", (quest_id,)
            ).fetchone()
            if quest is None:
                return error("This quest is not available.", 404)
            student = current_student(connection)
            attempt_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO attempts (id, student_id, quest_id) VALUES (?, ?, ?)",
                (attempt_id, student["id"], quest_id),
            )
            questions = json.loads(quest["questions_json"])
        return jsonify(
            {
                "attempt_id": attempt_id,
                "quest": quest_summary(quest),
                "questions": [public_question(question) for question in questions],
            }
        ), 201

    @app.post("/api/attempts/<attempt_id>/answers")
    @require_role("student")
    def submit_answer(attempt_id: str):
        body = request.get_json(silent=True) or {}
        question_index = body.get("question_index")
        answer_index = body.get("answer_index")
        if type(question_index) is not int or type(answer_index) is not int:
            return error("Choose an answer from the current question.", 400)
        with closing(connect_db()) as connection, connection:
            student = current_student(connection)
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE id = ? AND student_id = ?",
                (attempt_id, student["id"]),
            ).fetchone()
            if attempt is None:
                return error("This quiz attempt was not found. Start the quest again.", 404)
            if attempt["completed_at"]:
                return error("This quest attempt is already complete.", 409)
            questions = json.loads(
                connection.execute(
                    "SELECT questions_json FROM quests WHERE id = ?", (attempt["quest_id"],)
                ).fetchone()["questions_json"]
            )
            expected_index = connection.execute(
                "SELECT COUNT(*) FROM attempt_answers WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()[0]
            if question_index != expected_index or question_index >= len(questions):
                return error("Answer the questions in order, one at a time.", 409)
            question = questions[question_index]
            if answer_index < 0 or answer_index >= len(question["options"]):
                return error("That answer is not one of the available choices.", 400)
            is_correct = answer_index == question["answer"]
            gained_xp = 20 if is_correct else 0
            connection.execute(
                "INSERT INTO attempt_answers (attempt_id, question_index, answer_index, is_correct) VALUES (?, ?, ?, ?)",
                (attempt_id, question_index, answer_index, int(is_correct)),
            )
            if gained_xp:
                connection.execute(
                    "UPDATE students SET xp = xp + ? WHERE id = ?",
                    (gained_xp, student["id"]),
                )
        return jsonify(
            {
                "correct": is_correct,
                "explanation": question["explanation"],
                "xp_earned": gained_xp,
                "xp_total": student["xp"] + gained_xp,
                "next_question": question_index + 1,
                "question_count": len(questions),
            }
        )

    @app.post("/api/attempts/<attempt_id>/challenge")
    @require_role("student")
    def submit_challenge(attempt_id: str):
        body = request.get_json(silent=True) or {}
        source = body.get("code")
        if not isinstance(source, str):
            return error("Submit your code as text.", 400)
        with closing(connect_db()) as connection, connection:
            student = current_student(connection)
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE id = ? AND student_id = ?",
                (attempt_id, student["id"]),
            ).fetchone()
            if attempt is None:
                return error("This quest attempt was not found. Start the quest again.", 404)
            if attempt["completed_at"]:
                return error("This quest attempt is already complete.", 409)
            quest = connection.execute(
                "SELECT * FROM quests WHERE id = ?", (attempt["quest_id"],)
            ).fetchone()
            question_count = len(json.loads(quest["questions_json"]))
            answered_count = connection.execute(
                "SELECT COUNT(*) FROM attempt_answers WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()[0]
            if answered_count != question_count:
                return error("Finish the quiz before submitting the coding challenge.", 409)
            try:
                execution = run_code_in_sandbox(quest["language"], source)
            except ValueError as exception:
                return error(str(exception), 400)
            except RuntimeError as exception:
                return error(str(exception), 503)
            output = execution["output"]
            if execution["exit_code"] != 0:
                return jsonify({
                    "passed": False,
                    "feedback": "Your code did not finish successfully. Check the output and fix the error.",
                    "output": output,
                }), 200
            if output.strip() != quest["expected_output"].strip():
                return jsonify({
                    "passed": False,
                    "feedback": "Your program ran, but its output does not match the expected result yet.",
                    "output": output,
                }), 200
            feedback = "Great work! Your program ran successfully and produced the expected output."

            today = date.today()
            last_completed = student["last_completed_date"]
            if last_completed != today.isoformat():
                streak = student["streak"] + 1 if last_completed == (today - timedelta(days=1)).isoformat() else 1
                connection.execute(
                    "UPDATE students SET xp = xp + 70, streak = ?, last_completed_date = ? WHERE id = ?",
                    (streak, today.isoformat(), student["id"]),
                )
            else:
                connection.execute(
                    "UPDATE students SET xp = xp + 70 WHERE id = ?",
                    (student["id"],),
                )
            connection.execute(
                "UPDATE attempts SET challenge_passed = 1, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (attempt_id,),
            )
            connection.execute(
                "INSERT INTO activities (student_id, quest_id, xp_earned) VALUES (?, ?, ?)",
                (student["id"], quest["id"], 70 + 20 * sum(
                    row["is_correct"] for row in connection.execute(
                        "SELECT is_correct FROM attempt_answers WHERE attempt_id = ?", (attempt_id,)
                    ).fetchall()
                )),
            )
            updated = connection.execute(
                "SELECT xp, streak FROM students WHERE id = ?", (student["id"],)
            ).fetchone()
        return jsonify(
            {
                "passed": True,
                "feedback": feedback,
                "output": output,
                "xp_earned": 70,
                "xp_total": updated["xp"],
                "streak": updated["streak"],
            }
        )

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_exception: RequestEntityTooLarge):
        return error("The upload is too large. Choose a PDF smaller than 20 MB.", 413)

    @app.errorhandler(sqlite3.Error)
    def database_error(exception: sqlite3.Error):
        app.logger.exception("Database request failed", exc_info=exception)
        return error("The classroom database could not complete that request. Please try again.", 500)

    @app.errorhandler(500)
    def internal_error(_exception: Exception):
        return error("The server could not complete that request. Please try again.", 500)

    initialize_database()
    return app


def quest_summary_from_dict(quest_id: str, quest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": quest_id,
        "title": quest["title"],
        "topic": quest["topic"],
        "description": quest["description"],
        "challenge": quest["challenge"],
        "expected_output": quest["expected_output"],
        "language": quest["language"],
        "file_name": quest["file_name"],
        "question_count": len(quest["questions"]),
        "published_at": None,
    }


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
