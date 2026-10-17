(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const LANGUAGE_NAMES = {
    python: "Python", javascript: "JavaScript", java: "Java", c: "C",
    cpp: "C++", csharp: "C#", go: "Go", ruby: "Ruby"
  };
  const authScreen = $("#auth-screen");
  const appShell = $("#app-shell");
  const studentView = $("#student-view");
  const teacherView = $("#teacher-view");
  const secondaryView = $("#secondary-view");
  const pdfInput = $("#pdf-upload");
  const dropZone = $("#drop-zone");
  const generateButton = $("#generate-quest");
  const uploadMessage = $("#upload-message");
  const modal = $("#game-modal");
  const gameStage = $("#game-stage");

  let loggedUser = null;
  let authMode = "login";
  let currentFile = null;
  let draftQuest = null;
  let activeQuest = null;
  let attemptId = null;
  let questions = [];
  let gameStep = 0;
  let correctAnswers = 0;
  let earnedXp = 0;
  let toastTimeout;

  async function api(path, options = {}) {
    if (window.location.protocol === "file:") {
      throw new Error(serverConnectionMessage());
    }
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.error || `The server returned an error (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function serverConnectionMessage() {
    if (window.location.protocol === "file:") {
      return "Open ByteQuest at http://127.0.0.1:5000. Start it with `python app.py`; opening index.html directly cannot generate quests.";
    }
    return "Could not connect to the Python server. Start it with `python app.py`, then reload this page.";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
  }

  function showToast(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.remove("hidden");
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => toast.classList.add("hidden"), 3500);
  }

  function showMessage(message, isSuccess) {
    uploadMessage.textContent = message;
    uploadMessage.classList.toggle("success", Boolean(isSuccess));
  }

  function setView(view) {
    if (loggedUser && loggedUser.role === "teacher" && view !== "teacher" && view !== "leaderboard") {
      view = "teacher";
    }
    if (loggedUser && loggedUser.role === "student" && view === "teacher") return;
    studentView.classList.add("hidden");
    teacherView.classList.add("hidden");
    secondaryView.classList.add("hidden");
    document.querySelectorAll(".nav-link").forEach((button) => button.classList.remove("active"));

    if (view === "teacher") {
      teacherView.classList.remove("hidden");
      $("#teacher-mode").classList.add("selected");
      $("#teacher-mode").setAttribute("aria-selected", "true");
      $("#student-mode").classList.remove("selected");
      $("#student-mode").setAttribute("aria-selected", "false");
      $("#breadcrumb-page").textContent = "Teacher Studio";
      return;
    }

    $("#student-mode").classList.add("selected");
    $("#student-mode").setAttribute("aria-selected", "true");
    $("#teacher-mode").classList.remove("selected");
    $("#teacher-mode").setAttribute("aria-selected", "false");
    if (view === "dashboard") {
      studentView.classList.remove("hidden");
      $("#breadcrumb-page").textContent = "Dashboard";
      document.querySelector('[data-view="dashboard"]').classList.add("active");
      return;
    }

    secondaryView.classList.remove("hidden");
    document.querySelector(`[data-view="${view}"]`)?.classList.add("active");
    if (view === "leaderboard") {
      $("#breadcrumb-page").textContent = "Leaderboard";
      $("#secondary-kicker").textContent = "PYTHON PIONEERS · ROOM 204";
      $("#secondary-title").innerHTML = 'A little friendly <span>competition.</span>';
      $("#secondary-subtitle").textContent = "Cheer on your classmates and keep climbing.";
      renderLeaderboard();
    } else {
      $("#breadcrumb-page").textContent = "Learning Path";
      $("#secondary-kicker").textContent = "YOUR LEARNING PATH";
      $("#secondary-title").innerHTML = 'Keep collecting <span>small wins.</span>';
      $("#secondary-subtitle").textContent = "Your coding adventure, one concept at a time.";
      const questLine = activeQuest
        ? `Your current classroom quest is ${escapeHtml(activeQuest.title)} (${escapeHtml(activeQuest.topic)}).`
        : "Your teacher has not published a quest yet.";
      $("#secondary-card").innerHTML = `<h3>⌘ &nbsp;Coding Basics</h3><p>Work through your classroom's coding quests, one concept at a time.</p><p>${questLine}</p><button class="primary-button" id="path-start" ${activeQuest ? "" : "disabled"}>Continue learning <span>→</span></button>`;
      $("#path-start").addEventListener("click", openGame);
    }
  }

  function renderStudent(student) {
    const name = student.name;
    const xp = Number(student.xp);
    const level = Math.floor(xp / 200) + 1;
    const progress = xp % 200;
    $("#student-name").textContent = name;
    $("#profile-name").textContent = name;
    $("#profile-level").textContent = `Level ${String(level).padStart(2, "0")} · Explorer`;
    $("#level-label").textContent = `LVL ${String(level).padStart(2, "0")}`;
    $("#xp-count").textContent = xp.toLocaleString();
    $("#level-xp").textContent = `${xp.toLocaleString()} XP`;
    $("#next-level-xp").textContent = `${200 - progress} XP to level ${level + 1}`;
    $("#level-progress-bar").style.width = `${progress / 2}%`;
    $("#streak-count").textContent = String(student.streak);
    $("#streak-days").textContent = String(student.streak);
    const dailyCount = Number(student.completed_today);
    $("#daily-progress-label").textContent = `${Math.min(dailyCount, 3)} / 3`;
    $(".daily-progress span").style.width = `${Math.min(dailyCount, 3) / 3 * 100}%`;
    $(".daily-card > p").textContent = dailyCount >= 3
      ? "Daily goal complete. Amazing work!"
      : `${3 - dailyCount} more ${3 - dailyCount === 1 ? "quest" : "quests"} to hit today's goal.`;
  }

  function updateStudentQuest(quest) {
    activeQuest = quest;
    $("#quest-language-label").textContent = quest
      ? `${LANGUAGE_NAMES[quest.language] || quest.language} QUEST`.toUpperCase()
      : "CODING QUEST";
    if (!quest) {
      $("#quest-title").textContent = "No quest published yet";
      $("#quest-description").textContent = "Your teacher's next coding adventure will appear here.";
      $("#quest-question-count").textContent = "0";
      $("#start-quest").disabled = true;
      $("#start-quest").innerHTML = "Waiting for a class quest <span>⌛</span>";
      $("#class-banner-title").textContent = "No new class quests — yet!";
      $("#class-banner-copy").textContent = "When your teacher shares a lesson, it’ll show up right here.";
      $("#find-class").textContent = "Explore class quests →";
      return;
    }
    $("#quest-title").textContent = quest.title;
    $("#quest-description").innerHTML = `${escapeHtml(quest.description)} <strong>${escapeHtml(quest.topic)}</strong>.`;
    $("#quest-question-count").textContent = String(quest.question_count);
    $("#start-quest").disabled = false;
    $("#start-quest").innerHTML = "Play classroom quest <span>→</span>";
    $("#class-banner-title").textContent = quest.title;
    $("#class-banner-copy").textContent = `Your teacher shared a quest about ${quest.topic}. Jump in and earn up to 150 XP!`;
    $("#find-class").textContent = "Open leaderboard →";
  }

  function renderActivities(activities) {
    const container = $("#activities-list");
    if (!activities.length) {
      container.innerHTML = '<p class="empty-activity">Complete a quest and your wins will show up here.</p>';
      return;
    }
    container.innerHTML = activities.map((activity) => (
      `<div class="activity-item"><span class="activity-icon green">✓</span><span><strong>${escapeHtml(activity.title)}</strong><small>${escapeHtml(activity.topic)} · ${new Date(activity.completed_at + "Z").toLocaleDateString()}</small></span><b>+${Number(activity.xp_earned)} XP</b></div>`
    )).join("");
  }

  async function renderLeaderboard() {
    const container = $("#secondary-card");
    container.innerHTML = "<p>Loading the classroom leaderboard…</p>";
    try {
      const data = await api("/api/leaderboard");
      if (!data.players.length) {
        container.innerHTML = "<h3>🏆 &nbsp;This week's top coders</h3><p>Complete a classroom quest to be the first on the board.</p>";
        return;
      }
      const rows = data.players.map((player, index) => (
        `<div class="leaderboard-row"><span>${index + 1}.</span><strong>${escapeHtml(player.name)}</strong><b>${Number(player.xp).toLocaleString()} XP</b></div>`
      )).join("");
      container.innerHTML = `<h3>🏆 &nbsp;This week's top coders</h3>${rows}<p>Every published classroom quest is a chance to earn XP.</p>`;
    } catch (error) {
      container.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
  }

  async function refreshDashboard() {
    const data = await api("/api/bootstrap");
    if (data.student) renderStudent(data.student);
    updateStudentQuest(data.quest);
    renderActivities(data.activities);
  }

  function acceptFile(file) {
    if (!file) return;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      showMessage("Please choose a PDF file.", false);
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      showMessage("That PDF is too large. Please choose a file under 20 MB.", false);
      return;
    }
    currentFile = file;
    draftQuest = null;
    $("#upload-title").textContent = file.name;
    $("#upload-help").textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB · PDF selected`;
    generateButton.disabled = false;
    $("#preview-empty").classList.remove("hidden");
    $("#preview-content").classList.add("hidden");
    $("#preview-status").textContent = "READY TO GENERATE";
    $("#preview-status").classList.remove("ready");
    showMessage("PDF selected. Generate and review the draft before publishing.", true);
  }

  async function generateQuest() {
    if (!currentFile) {
      showMessage("Choose a lecture PDF before generating a quest.", false);
      return;
    }
    generateButton.disabled = true;
    generateButton.firstChild.textContent = "Reading lecture… ";
    showMessage("The classroom server is reading the PDF…", true);
    const form = new FormData();
    form.append("pdf", currentFile);
    form.append("language", $("#quest-language").value);
    try {
      draftQuest = await api("/api/quests/drafts", { method: "POST", body: form });
      $("#preview-quest-name").textContent = draftQuest.title;
      $("#preview-quest-description").textContent = `${draftQuest.description}. Based on ${draftQuest.file_name}.`;
      $("#preview-language-label").textContent = `${LANGUAGE_NAMES[draftQuest.language] || draftQuest.language} CHALLENGE`.toUpperCase();
      $("#preview-challenge-title").textContent = `${LANGUAGE_NAMES[draftQuest.language] || draftQuest.language} · ${draftQuest.challenge}`;
      $("#preview-question-count").textContent = `${draftQuest.question_count} multiple-choice questions`;
      $("#preview-status").textContent = "DRAFT READY";
      $("#preview-status").classList.add("ready");
      $("#preview-empty").classList.add("hidden");
      $("#preview-content").classList.remove("hidden");
      showMessage(`Found ${draftQuest.topic} in ${draftQuest.file_name}. Review the draft before publishing.`, true);
    } catch (error) {
      console.error("Unable to generate a classroom quest from this PDF.", error);
      showMessage(error.message, false);
      $("#preview-status").textContent = "COULDN'T READ PDF";
      $("#preview-status").classList.remove("ready");
    } finally {
      generateButton.disabled = !currentFile;
      generateButton.firstChild.textContent = "Generate classroom quest ";
    }
  }

  async function publishQuest() {
    if (!draftQuest) return;
    const button = $("#publish-quest");
    button.disabled = true;
    try {
      await api(`/api/quests/${encodeURIComponent(draftQuest.id)}/publish`, { method: "POST" });
      await refreshDashboard();
      setView("dashboard");
      showToast("Quest published! Your students can now find it on their dashboard.");
    } catch (error) {
      showMessage(error.message, false);
    } finally {
      button.disabled = false;
    }
  }

  async function openGame() {
    if (!activeQuest) {
      showToast("Your teacher has not published a quest yet.");
      return;
    }
    const button = $("#start-quest");
    button.disabled = true;
    try {
      const attempt = await api(`/api/quests/${encodeURIComponent(activeQuest.id)}/attempts`, { method: "POST" });
      attemptId = attempt.attempt_id;
      activeQuest = attempt.quest;
      questions = attempt.questions;
      gameStep = 0;
      correctAnswers = 0;
      earnedXp = 0;
      $("#game-title").textContent = activeQuest.title;
      $("#game-xp-label").innerHTML = "✦ &nbsp;0 XP";
      modal.classList.remove("hidden");
      document.body.style.overflow = "hidden";
      showQuestion();
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = !activeQuest;
    }
  }

  function closeGame() {
    modal.classList.add("hidden");
    document.body.style.overflow = "";
  }

  function showQuestion() {
    if (gameStep >= questions.length) {
      showChallenge();
      return;
    }
    const question = questions[gameStep];
    $("#game-step-label").textContent = `QUESTION ${gameStep + 1} OF ${questions.length}`;
    $("#game-progress-bar").style.width = `${(gameStep / (questions.length + 1)) * 100}%`;
    gameStage.innerHTML = `<span class="game-eyebrow">QUICK-FIRE QUIZ</span><h2 class="game-stage-title">${question.question}</h2><p class="game-question-copy">Choose the best answer to earn XP.</p><div class="answer-list">${question.options.map((option, index) => `<button class="answer-option" data-answer="${index}"><span class="option-letter">${String.fromCharCode(65 + index)}</span>${escapeHtml(option)}</button>`).join("")}</div><p class="feedback-message" id="answer-feedback" aria-live="polite"></p><button class="primary-button game-next hidden" id="game-next">Next question <span>→</span></button>`;
    gameStage.querySelectorAll(".answer-option").forEach((button) => button.addEventListener("click", () => selectAnswer(Number(button.dataset.answer), button)));
    $("#game-next").addEventListener("click", () => {
      gameStep += 1;
      showQuestion();
    });
  }

  async function selectAnswer(selected, selectedButton) {
    const buttons = gameStage.querySelectorAll(".answer-option");
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const result = await api(`/api/attempts/${encodeURIComponent(attemptId)}/answers`, {
        method: "POST",
        body: JSON.stringify({ question_index: gameStep, answer_index: selected })
      });
      const feedback = $("#answer-feedback");
      if (result.correct) {
        correctAnswers += 1;
        earnedXp += result.xp_earned;
        selectedButton.classList.add("correct");
        feedback.textContent = `Nice work! ${result.explanation}`;
        feedback.classList.add("good");
      } else {
        selectedButton.classList.add("wrong");
        feedback.textContent = `Not quite. ${result.explanation}`;
        feedback.classList.add("bad");
      }
      $("#xp-count").textContent = Number(result.xp_total).toLocaleString();
      $("#game-xp-label").innerHTML = `✦ &nbsp;${earnedXp} XP`;
      $("#game-next").classList.remove("hidden");
      $("#game-next").firstChild.textContent = gameStep === questions.length - 1 ? "Try the coding challenge " : "Next question ";
    } catch (error) {
      buttons.forEach((button) => { button.disabled = false; });
      showToast(error.message);
    }
  }

  function showChallenge() {
    const topic = activeQuest.topic;
    const starters = {
      python: "for number in range(1, 6):\n    print(number)",
      javascript: "for (let number = 1; number <= 5; number++) {\n  console.log(number);\n}",
      java: "public class Main {\n  public static void main(String[] args) {\n    for (int number = 1; number <= 5; number++) {\n      System.out.println(number);\n    }\n  }\n}",
      c: "#include <stdio.h>\nint main(void) {\n  for (int number = 1; number <= 5; number++) printf(\"%d\\n\", number);\n  return 0;\n}",
      cpp: "#include <iostream>\nint main() {\n  for (int number = 1; number <= 5; number++) std::cout << number << '\\n';\n}",
      csharp: "using System;\nfor (int number = 1; number <= 5; number++)\n{\n    Console.WriteLine(number);\n}",
      go: "package main\nimport \"fmt\"\nfunc main() {\n  for number := 1; number <= 5; number++ { fmt.Println(number) }\n}",
      ruby: "1.upto(5) { |number| puts number }"
    };
    const expectedOutput = activeQuest.expected_output;
    const starter = topic.includes("loop") ? starters[activeQuest.language] || "" : `Write your ${activeQuest.language} solution here`;
    $("#game-step-label").textContent = "FINAL CHALLENGE";
    $("#game-progress-bar").style.width = `${(questions.length / (questions.length + 1)) * 100}%`;
    const languageName = LANGUAGE_NAMES[activeQuest.language] || activeQuest.language;
    gameStage.innerHTML = `<span class="game-eyebrow">CODING CHALLENGE · ${escapeHtml(languageName.toUpperCase())}</span><h2 class="game-stage-title">${escapeHtml(topic)}</h2><p class="section-kicker">PROBLEM</p><p class="game-question-copy">${escapeHtml(activeQuest.challenge)}</p><p class="section-kicker">EXPECTED OUTPUT</p><pre class="challenge-output">${escapeHtml(expectedOutput)}</pre><textarea class="code-editor" id="code-answer" aria-label="Your ${escapeHtml(languageName)} code" spellcheck="false" placeholder="${escapeHtml(starter)}"></textarea><p class="challenge-hint">Your code runs in an isolated Docker sandbox. Output must match the expected result to complete this challenge.</p><p class="feedback-message" id="challenge-feedback" aria-live="polite"></p><p class="section-kicker">YOUR PROGRAM OUTPUT</p><pre class="challenge-output" id="challenge-output">Run your solution to see its output.</pre><button class="primary-button" id="submit-code">Run and check solution <span>✓</span></button>`;
    $("#submit-code").addEventListener("click", submitChallenge);
  }

  async function submitChallenge() {
    const button = $("#submit-code");
    const source = $("#code-answer").value;
    button.disabled = true;
    try {
      const result = await api(`/api/attempts/${encodeURIComponent(attemptId)}/challenge`, {
        method: "POST",
        body: JSON.stringify({ code: source })
      });
      $("#challenge-output").textContent = result.output || "(no output)";
      if (!result.passed) {
        const feedback = $("#challenge-feedback");
        feedback.textContent = result.feedback;
        feedback.classList.add("bad");
        $("#code-answer").focus();
        return;
      }
      earnedXp += result.xp_earned;
      await refreshDashboard();
      finishGame(result.output);
    } catch (error) {
      showToast(error.message);
    } finally {
      if ($("#submit-code")) $("#submit-code").disabled = false;
    }
  }

  function finishGame(output) {
    $("#game-step-label").textContent = "QUEST COMPLETE";
    $("#game-progress-bar").style.width = "100%";
    gameStage.innerHTML = `<div class="game-result"><div class="result-star">✦</div><span class="game-eyebrow">QUEST COMPLETE</span><h2>You're getting good at this.</h2><p>You got ${correctAnswers} out of ${questions.length} quiz questions right and completed the coding challenge. Keep that streak going!</p><p class="section-kicker">PROGRAM OUTPUT</p><pre class="challenge-output">${escapeHtml(output || "(no output)")}</pre><div class="result-xp">+${earnedXp} XP earned</div><button class="primary-button" id="finish-game">Back to dashboard <span>→</span></button></div>`;
    $("#game-xp-label").innerHTML = `✦ &nbsp;${earnedXp} XP`;
    $("#finish-game").addEventListener("click", closeGame);
  }

  async function renameStudent() {
    const currentName = $("#profile-name").textContent;
    const name = window.prompt("What name should your classmates see?", currentName);
    if (name === null || !name.trim()) return;
    try {
      await api("/api/students/me", { method: "PUT", body: JSON.stringify({ name: name.trim() }) });
      await refreshDashboard();
      if (!secondaryView.classList.contains("hidden") && $("#breadcrumb-page").textContent === "Leaderboard") {
        renderLeaderboard();
      }
    } catch (error) {
      showToast(error.message);
    }
  }

  function setAuthMode(mode) {
    authMode = mode;
    const registering = mode === "register";
    $("#auth-title").innerHTML = registering
      ? "Create your <span>ByteQuest account.</span>"
      : "Sign in to your <span>classroom.</span>";
    $("#auth-name-field").classList.toggle("hidden", !registering);
    $("#auth-name").required = registering;
    $("#auth-password").autocomplete = registering ? "new-password" : "current-password";
    $("#auth-submit").innerHTML = registering ? "Create account <span>→</span>" : "Sign in <span>→</span>";
    $("#auth-switch-prompt").textContent = registering ? "Already have an account?" : "New to ByteQuest?";
    $("#auth-switch").textContent = registering ? "Sign in" : "Create an account";
    $("#auth-error").textContent = "";
  }

  async function showApplication(user) {
    loggedUser = user;
    authScreen.classList.add("hidden");
    appShell.classList.remove("hidden");
    $(".mode-switch").classList.add("hidden");
    $("#teacher-mode").classList.toggle("hidden", user.role !== "teacher");
    $("#student-mode").classList.toggle("hidden", user.role !== "student");
    $("#profile-button").classList.toggle("hidden", user.role !== "student");
    $(".streak").classList.toggle("hidden", user.role !== "student");
    $(".xp-pill").classList.toggle("hidden", user.role !== "student");
    $(".mode-copy h1").innerHTML = user.role === "teacher"
      ? 'Build a classroom <span>quest.</span>'
      : 'Choose your <span>adventure.</span>';
    $("#breadcrumb-page").textContent = user.role === "teacher" ? "Teacher Studio" : "Dashboard";
    try {
      await refreshDashboard();
      setView(user.role === "teacher" ? "teacher" : "dashboard");
    } catch (error) {
      console.error("Unable to load the ByteQuest dashboard.", error);
      showToast(error.message);
    }
  }

  function showAuthentication(message = "") {
    loggedUser = null;
    appShell.classList.add("hidden");
    authScreen.classList.remove("hidden");
    setAuthMode("login");
    $("#auth-error").textContent = message;
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
      showAuthentication();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function authenticate(event) {
    event.preventDefault();
    const submit = $("#auth-submit");
    submit.disabled = true;
    $("#auth-error").textContent = "";
    const registering = authMode === "register";
    const body = {
      email: $("#auth-email").value.trim(),
      password: $("#auth-password").value,
      role: $("#auth-role").value
    };
    if (registering) body.name = $("#auth-name").value.trim();
    try {
      const result = await api(registering ? "/api/auth/register" : "/api/auth/login", {
        method: "POST",
        body: JSON.stringify(body)
      });
      await showApplication(result.user);
    } catch (error) {
      $("#auth-error").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  }

  document.querySelectorAll(".nav-link").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  document.querySelectorAll('[data-view="learn"]').forEach((button) => button.addEventListener("click", () => setView("learn")));
  $("#student-mode").addEventListener("click", () => setView("dashboard"));
  $("#teacher-mode").addEventListener("click", () => setView("teacher"));
  $("#classroom-shortcut").addEventListener("click", () => setView("leaderboard"));
  $("#find-class").addEventListener("click", () => setView("leaderboard"));
  $("#resume-path").addEventListener("click", openGame);
  $("#start-quest").addEventListener("click", openGame);
  $("#profile-button").addEventListener("click", renameStudent);
  $("#logout-button").addEventListener("click", logout);
  $("#auth-form").addEventListener("submit", authenticate);
  $("#auth-switch").addEventListener("click", () => setAuthMode(authMode === "login" ? "register" : "login"));
  pdfInput.addEventListener("change", (event) => acceptFile(event.target.files[0]));
  generateButton.addEventListener("click", generateQuest);
  $("#publish-quest").addEventListener("click", publishQuest);
  $("#remove-pdf").addEventListener("click", () => {
    currentFile = null;
    draftQuest = null;
    pdfInput.value = "";
    $("#upload-title").textContent = "Drop your lecture PDF here";
    $("#upload-help").innerHTML = 'or <u>browse files</u> · PDF up to 20 MB';
    generateButton.disabled = true;
    $("#preview-empty").classList.remove("hidden");
    $("#preview-content").classList.add("hidden");
    $("#preview-status").textContent = "WAITING FOR PDF";
    $("#preview-status").classList.remove("ready");
    showMessage("", false);
  });
  $("#close-game").addEventListener("click", closeGame);
  modal.addEventListener("click", (event) => { if (event.target === modal) closeGame(); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) closeGame();
  });
  dropZone.addEventListener("dragover", (event) => { event.preventDefault(); dropZone.classList.add("dragging"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
    acceptFile(event.dataTransfer.files[0]);
  });

  const initialDate = new Date();
  $("#today-date").textContent = new Intl.DateTimeFormat("en", {
    weekday: "long", month: "long", day: "numeric"
  }).format(initialDate).toUpperCase();
  api("/api/auth/me")
    .then((result) => showApplication(result.user))
    .catch((error) => {
      if (error.status === 401) {
        showAuthentication();
        return;
      }
      console.error("Unable to connect to the ByteQuest server.", error);
      showAuthentication(serverConnectionMessage());
    });
})();
