const state = {
  repo: "",
  pr: "",
  pollMs: 1000,
  hold: false,
  changes: [],
  comments: [],
  hunks: [],
  file: null,
  editing: false,
  dirty: false,
  stack: [],
  selectedLine: null,
  prMeta: null,
};

const $ = (id) => document.getElementById(id);

function query() {
  const params = new URLSearchParams(window.location.search);
  state.repo = params.get("repo") || "";
  state.pr = params.get("pr") || "";
}

function repoQuery() {
  return "repo=" + encodeURIComponent(state.repo);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "request failed");
  }
  return data;
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ repo: state.repo }, body)),
  });
}

function notice(message) {
  const node = $("notice");
  node.hidden = !message;
  node.textContent = message || "";
}

function basename(path) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

async function boot() {
  query();
  if (!state.repo) {
    notice("Open a repository with the kensa command.");
    return;
  }
  $("repo-name").textContent = state.repo;
  $("repo-name").title = state.repo;
  try {
    const health = await api("/api/health");
    state.pollMs = health.pollMs || state.pollMs;
    if (state.pr) {
      state.prMeta = await api("/api/pr?" + repoQuery() + "&number=" + encodeURIComponent(state.pr));
      showPullRequest();
    }
    await refresh();
    const first = state.pr ? (state.prMeta.files[0] || {}).path : (state.changes[0] || {}).path;
    if (first) {
      await openPath(first, null, false);
    } else {
      $("code").innerHTML = "";
      $("code").append(el("p", "empty", state.pr ? "This pull request has no files." : "No changes against HEAD."));
    }
  } catch (error) {
    notice(error.message);
  }
  window.setInterval(() => {
    refresh().catch((error) => notice(error.message));
  }, state.pollMs);
  bind();
}

function showPullRequest() {
  const bar = $("pr-bar");
  bar.hidden = false;
  const meta = state.prMeta;
  $("pr-title").textContent = "PR #" + meta.number + " " + meta.title + (meta.checkedOut ? " · checked out" : " · read only");
  $("list-heading").textContent = "Pull request";
}

async function refresh() {
  const snap = await api("/api/snapshot?" + repoQuery());
  state.hold = snap.hold;
  state.comments = snap.comments;
  state.hunks = snap.hunks;
  if (!state.pr) {
    state.changes = snap.changes;
  }
  $("hold").textContent = state.hold ? "Holding" : "Hold";
  renderSidebar();
  const signature = JSON.stringify({
    comments: state.comments,
    hunks: state.hunks,
  });
  const commentsChanged = signature !== state.viewSignature;
  if (!state.file || state.dirty || state.editing) {
    renderComments();
    state.viewSignature = signature;
    return;
  }
  const current = state.changes.find((item) => item.path === state.file.path);
  if (!state.pr && current && current.hash && current.hash !== state.file.hash) {
    await openPath(state.file.path, state.selectedLine, false);
    state.viewSignature = signature;
    return;
  }
  if (commentsChanged) {
    const main = $("main");
    const top = main.scrollTop;
    renderFile();
    renderComments();
    main.scrollTop = top;
  } else {
    renderComments();
  }
  state.viewSignature = signature;
}

function renderSidebar() {
  const list = $("file-list");
  list.replaceChildren();
  const rows = state.pr ? state.prMeta.files : state.changes;
  if (!rows.length) {
    list.append(el("li", "meta", state.pr ? "No files in this diff." : "Working tree matches HEAD."));
    return;
  }
  rows.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    if (state.file && state.file.path === item.path) {
      button.className = "active";
    }
    const count = state.comments.filter((comment) => comment.path === item.path).length;
    button.textContent = (item.status ? item.status + " " : "") + item.path + (count ? " (" + count + ")" : "");
    button.addEventListener("click", () => {
      openPath(item.path, null, true).catch((error) => notice(error.message));
    });
    const li = document.createElement("li");
    li.append(button);
    list.append(li);
  });
}

async function openPath(path, line, push) {
  if (push && state.file) {
    state.stack.push({ path: state.file.path, line: state.selectedLine });
  }
  const inPullRequest = state.pr && state.prMeta && state.prMeta.files.some((item) => item.path === path);
  const url = inPullRequest
    ? "/api/pr/file?" + repoQuery() + "&number=" + encodeURIComponent(state.pr) + "&path=" + encodeURIComponent(path)
    : "/api/file?" + repoQuery() + "&path=" + encodeURIComponent(path);
  state.file = await api(url);
  state.editing = false;
  state.dirty = false;
  state.selectedLine = line;
  $("back").disabled = state.stack.length === 0;
  renderFile();
  renderSidebar();
  renderComments();
  if (line) {
    const node = document.getElementById("line-" + line);
    if (node) {
      node.scrollIntoView({ block: "center" });
    }
  }
  loadOutline(path).catch(() => {});
}

async function loadOutline(path) {
  const data = await api("/api/outline?" + repoQuery() + "&path=" + encodeURIComponent(path));
  const select = $("outline");
  select.replaceChildren();
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "Outline";
  select.append(blank);
  data.outline.forEach((item) => {
    const option = document.createElement("option");
    option.value = String(item.line);
    option.textContent = item.name + ":" + item.line;
    select.append(option);
  });
}

function renderFile() {
  const file = state.file;
  $("file-bar").hidden = false;
  $("file-path").textContent = file.path;
  const flag = $("file-flag");
  if (!file.editable) {
    flag.hidden = false;
    flag.textContent = "Read only";
  } else if (file.inReview === false || file.status === "context") {
    flag.hidden = false;
    flag.textContent = "Context";
  } else {
    flag.hidden = true;
  }
  $("edit").hidden = state.editing || !file.editable;
  $("save").hidden = !state.editing;
  $("cancel-edit").hidden = !state.editing;
  $("editor-wrap").hidden = !state.editing;
  $("code").hidden = state.editing;
  if (state.editing) {
    $("editor").value = file.content;
    return;
  }
  const code = $("code");
  code.replaceChildren();
  if (file.binary) {
    code.append(el("p", "empty", "Binary file. Kensa leaves it closed."));
    return;
  }
  const deletions = {};
  (file.deletions || []).forEach((item) => {
    (deletions[item.before] = deletions[item.before] || []).push(item.text);
  });
  const anchors = {};
  (file.anchors || []).forEach((item) => {
    (anchors[item.line] = anchors[item.line] || []).push(item);
  });
  const commentsAt = {};
  state.comments.filter((item) => item.path === file.path).forEach((item) => {
    (commentsAt[item.line] = commentsAt[item.line] || []).push(item);
  });
  file.rows.forEach((row) => {
    (anchors[row.num] || []).forEach((anchor) => code.append(hunkBar(file.path, anchor)));
    (deletions[row.num] || []).forEach((text) => code.append(ghostRow(text)));
    code.append(codeRow(row, commentsAt[row.num] || []));
  });
  const end = file.rows.length + 1;
  (deletions[end] || []).forEach((text) => code.append(ghostRow(text)));
  if (!file.rows.length) {
    code.append(el("p", "empty", "This file is empty."));
  }
}

function hunkBar(path, anchor) {
  const bar = document.createElement("div");
  bar.className = "hunk";
  const existing = state.hunks.find((item) => item.path === path && item.header === anchor.header);
  const label = document.createElement("code");
  label.textContent = anchor.header;
  bar.append(label);
  bar.append(markButton(path, anchor.header, "ok", "OK", existing));
  bar.append(markButton(path, anchor.header, "change", "Change", existing));
  return bar;
}

function markButton(path, header, mark, text, existing) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = existing && existing.mark === mark ? text + " ·" : text;
  button.addEventListener("click", () => {
    post("/api/hunks", { path: path, header: header, mark: mark })
      .then(refresh)
      .catch((error) => notice(error.message));
  });
  return button;
}

function ghostRow(text) {
  const row = document.createElement("div");
  row.className = "ghost";
  row.append(el("span", "gutter", "−"));
  const pre = document.createElement("pre");
  pre.className = "text";
  pre.textContent = text;
  row.append(pre);
  return row;
}

function codeRow(row, comments) {
  const line = document.createElement("div");
  line.className = "row " + row.kind + (state.selectedLine === row.num ? " selected" : "");
  line.id = "line-" + row.num;
  const gutter = document.createElement("button");
  gutter.type = "button";
  gutter.className = "gutter";
  comments.forEach((comment) => {
    const dot = document.createElement("span");
    dot.className = "badge " + comment.severity;
    gutter.append(dot);
  });
  gutter.append(document.createTextNode(String(row.num)));
  gutter.addEventListener("click", () => selectLine(row.num));
  const pre = document.createElement("pre");
  pre.className = "text";
  pre.textContent = row.text;
  line.append(gutter, pre);
  return line;
}

function selectLine(line) {
  state.selectedLine = line;
  $("comment-target").textContent = state.file.path + ":" + line;
  document.querySelectorAll(".row.selected").forEach((node) => node.classList.remove("selected"));
  const node = document.getElementById("line-" + line);
  if (node) {
    node.classList.add("selected");
  }
  $("comment-body").focus();
}

function renderComments() {
  const list = $("comment-list");
  list.replaceChildren();
  const rows = state.file
    ? state.comments.filter((item) => item.path === state.file.path)
    : state.comments;
  if (!rows.length) {
    list.append(el("li", "meta", "No comments yet."));
    return;
  }
  rows.forEach((comment) => {
    const item = document.createElement("li");
    const where = document.createElement("button");
    where.type = "button";
    where.className = "link";
    where.textContent = (comment.orphaned ? "moved " : "") + comment.path + ":" + comment.line + " " + comment.severity;
    where.addEventListener("click", () => {
      if (!state.file || state.file.path !== comment.path) {
        openPath(comment.path, comment.line, true).catch((error) => notice(error.message));
        return;
      }
      selectLine(comment.line);
    });
    const body = document.createElement("p");
    body.textContent = comment.body;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Dismiss";
    remove.addEventListener("click", () => {
      api("/api/comments?" + repoQuery() + "&id=" + encodeURIComponent(comment.id), { method: "DELETE" })
        .then(() => refresh())
        .catch((error) => notice(error.message));
    });
    item.append(where, body, remove);
    list.append(item);
  });
}

function bind() {
  $("comment-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.file || !state.selectedLine) {
      notice("Select a line first.");
      return;
    }
    post("/api/comments", {
      path: state.file.path,
      line: state.selectedLine,
      severity: $("severity").value,
      body: $("comment-body").value,
    }).then(async () => {
      $("comment-body").value = "";
      notice("");
      await refresh();
      await openPath(state.file.path, state.selectedLine, false);
    }).catch((error) => notice(error.message));
  });

  $("edit").addEventListener("click", () => {
    if (!state.file || !state.file.editable) {
      return;
    }
    state.editing = true;
    state.dirty = false;
    renderFile();
    $("editor").focus();
  });

  $("editor").addEventListener("input", () => {
    state.dirty = true;
  });

  $("cancel-edit").addEventListener("click", () => {
    state.editing = false;
    state.dirty = false;
    renderFile();
  });

  $("save").addEventListener("click", () => saveEditor());

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "s") {
      event.preventDefault();
      if (state.editing) {
        saveEditor();
      }
      return;
    }
    if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA")) {
      return;
    }
    if (event.key === "j" || event.key === "k") {
      moveChanged(event.key === "j" ? 1 : -1);
    }
  });

  $("hold").addEventListener("click", () => {
    post("/api/hold", { hold: !state.hold }).then(refresh).catch((error) => notice(error.message));
  });

  $("send").addEventListener("click", () => {
    post("/api/send", {}).then((result) => {
      notice("Sent to " + result.path);
    }).catch((error) => notice(error.message));
  });

  $("back").addEventListener("click", () => {
    const previous = state.stack.pop();
    if (!previous) {
      return;
    }
    openPath(previous.path, previous.line, false).catch((error) => notice(error.message));
  });

  $("outline").addEventListener("change", () => {
    const line = Number($("outline").value);
    if (line) {
      selectLine(line);
      const node = document.getElementById("line-" + line);
      if (node) {
        node.scrollIntoView({ block: "center" });
      }
    }
  });

  $("jump-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const typed = $("jump-symbol").value.trim();
    const selected = window.getSelection ? String(window.getSelection()).trim() : "";
    const symbol = typed || selected.split(/\s+/)[0] || "";
    if (!symbol) {
      notice("Type a symbol, or select one in the file.");
      return;
    }
    api("/api/jump?" + repoQuery() + "&symbol=" + encodeURIComponent(symbol))
      .then((data) => {
        const results = $("search-results");
        results.replaceChildren();
        if (!data.hits.length) {
          notice("No matches for " + symbol);
          return;
        }
        data.hits.forEach((hit) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = hit.path + ":" + hit.line + "  " + hit.text.trim();
          button.addEventListener("click", () => {
            results.replaceChildren();
            openPath(hit.path, hit.line, true).catch((error) => notice(error.message));
          });
          const li = document.createElement("li");
          li.append(button);
          results.append(li);
        });
        notice(data.hits.length + " match" + (data.hits.length === 1 ? "" : "es") + " for " + symbol);
        return openPath(data.hits[0].path, data.hits[0].line, true);
      })
      .catch((error) => notice(error.message));
  });

  const search = $("file-search");
  search.addEventListener("input", () => {
    const q = search.value.trim();
    const results = $("search-results");
    if (!q) {
      results.replaceChildren();
      return;
    }
    api("/api/files?" + repoQuery() + "&q=" + encodeURIComponent(q))
      .then((data) => {
        results.replaceChildren();
        data.files.forEach((path) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = path;
          button.addEventListener("click", () => {
            search.value = "";
            results.replaceChildren();
            openPath(path, null, true).catch((error) => notice(error.message));
          });
          const li = document.createElement("li");
          li.append(button);
          results.append(li);
        });
      })
      .catch((error) => notice(error.message));
  });

  $("submit-pr").addEventListener("click", () => {
    post("/api/pr/submit", {
      number: state.pr,
      verdict: $("verdict").value,
      summary: $("summary").value,
    }).then((result) => {
      notice("Submitted " + result.inline + " inline comments. " + (result.url || ""));
    }).catch((error) => notice(error.message));
  });
}

function saveEditor() {
  if (!state.file) {
    return;
  }
  api("/api/file?" + repoQuery(), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo: state.repo, path: state.file.path, content: $("editor").value }),
  }).then((file) => {
    state.file = file;
    state.editing = false;
    state.dirty = false;
    notice("Saved " + file.path);
    return refresh();
  }).then(() => {
    if (state.file) {
      renderFile();
    }
  }).catch((error) => notice(error.message));
}

function moveChanged(direction) {
  if (!state.file || state.editing) {
    return;
  }
  const lines = state.file.rows.filter((row) => row.kind === "add").map((row) => row.num);
  if (!lines.length) {
    return;
  }
  const current = state.selectedLine || 0;
  const next = direction > 0
    ? lines.find((line) => line > current) || lines[0]
    : [...lines].reverse().find((line) => line < current) || lines[lines.length - 1];
  selectLine(next);
  const node = document.getElementById("line-" + next);
  if (node) {
    node.scrollIntoView({ block: "center" });
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  node.textContent = text;
  return node;
}

boot();
