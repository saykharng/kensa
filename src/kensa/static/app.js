const SIDEBAR_KEY = "kensa.sidebar.collapsed";
const SIDEBAR_HIDE_LABEL = "Hide files";
const SIDEBAR_SHOW_LABEL = "Show files";
const THEME_KEY = "kensa.theme";
const THEME_DARK = "dark";
const THEME_BRIGHT = "bright";
const THEME_DARK_LABEL = "Dark";
const THEME_BRIGHT_LABEL = "Bright";
const SEVERITY_BUG = "bug";
const SEVERITY_SUGGESTION = "suggestion";
const SEVERITY_NIT = "nit";
const SEVERITIES = [SEVERITY_BUG, SEVERITY_SUGGESTION, SEVERITY_NIT];
const COMMENT_PLACEHOLDER = "Comment";
const COMMENT_SAVE = "Save";
const COMMENT_CANCEL = "Cancel";
const COMMENT_DISMISS = "Dismiss";
const COMMENT_MOVED = "moved";
const SEVERITY_LABEL = "Severity";
const PANE_OLD = "old";
const PANE_NEW = "new";
const MATCHES_BRANCH = "This branch matches ";
const MATCHES_BASE = "Working tree matches ";
const NO_CHANGES_AGAINST = "No changes against ";
const SCOPE_ALL = "all";
const ALL_COMMITS = "All commits";
const SHOW_FULL_FILE = "Full file";
const SHOW_CHANGES = "Changes only";
const PAIR_CONTEXT = "context";
const LINE_HIDDEN = " line hidden";
const LINES_HIDDEN = " lines hidden";

const state = {
  repo: "",
  branch: "",
  base: "",
  oneOffBase: "",
  commitChoice: "",
  scope: "",
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
  draft: null,
  branchMeta: null,
  fullFiles: {},
};

const $ = (id) => document.getElementById(id);

function query() {
  const params = new URLSearchParams(window.location.search);
  state.repo = params.get("repo") || "";
  state.branch = params.get("branch") || "";
  state.oneOffBase = params.get("base") || "";
  state.commitChoice = params.get("commit") || "";
  state.scope = params.get("scope") || "";
}

function rangeQuery() {
  if (state.commitChoice) {
    return "&commit=" + encodeURIComponent(state.commitChoice);
  }
  if (state.scope) {
    return "&scope=" + encodeURIComponent(state.scope);
  }
  return "";
}

function branchQuery(path) {
  let query = repoQuery() + "&name=" + encodeURIComponent(state.branch);
  if (state.oneOffBase) {
    query += "&base=" + encodeURIComponent(state.oneOffBase);
  }
  query += rangeQuery();
  if (path) {
    query += "&path=" + encodeURIComponent(path);
  }
  return query;
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
  applyTheme(readTheme());
  $("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    applyTheme(current === THEME_DARK ? THEME_BRIGHT : THEME_DARK);
  });
  setSidebarCollapsed(readSidebarCollapsed());
  if (!state.repo) {
    notice("Open a repository with the kensa command.");
    return;
  }
  $("repo-name").textContent = state.repo;
  $("repo-name").title = state.repo;
  try {
    const health = await api("/api/health");
    state.pollMs = health.pollMs || state.pollMs;
    if (state.branch) {
      state.branchMeta = await api("/api/branch?" + branchQuery());
      showRange(state.branchMeta);
    }
    await refresh();
    const first = state.branch ? (state.branchMeta.files[0] || {}).path : (state.changes[0] || {}).path;
    if (first) {
      await openPath(first, null, false);
    } else {
      $("code").replaceChildren();
      const empty = state.branch
        ? MATCHES_BRANCH + state.branchMeta.baseLabel + "."
        : NO_CHANGES_AGAINST + state.base + ".";
      $("code").append(el("p", "empty", empty));
    }
  } catch (error) {
    notice(error.message);
  }
  window.setInterval(() => {
    refresh().catch((error) => notice(error.message));
  }, state.pollMs);
  bind();
}

function showRange(meta) {
  const bar = $("pr-bar");
  bar.hidden = false;
  $("pr-title").textContent = meta.title || "";
  $("pr-title").title = meta.title || "";
  renderCommitSelect(meta);
  if (state.branch) {
    $("list-heading").textContent = "Branch";
    $("submit-controls").hidden = !meta.pullRequest;
  } else {
    $("list-heading").textContent = "Changes";
    $("submit-controls").hidden = true;
  }
}

function renderCommitSelect(meta) {
  const label = $("commit-label");
  const select = $("commit-select");
  const commits = meta.commits || [];
  if (!commits.length) {
    label.hidden = true;
    return;
  }
  label.hidden = false;
  const signature = commits.map((item) => item.short).join(" ");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = SCOPE_ALL;
    all.textContent = ALL_COMMITS;
    select.append(all);
    commits.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.short;
      option.textContent = item.short + " " + item.subject;
      select.append(option);
    });
    select.dataset.signature = signature;
  }
  let next = SCOPE_ALL;
  if (state.commitChoice) {
    next = state.commitChoice;
  } else if (state.scope !== SCOPE_ALL && meta.commit) {
    next = meta.commit;
  }
  if (select.value !== next) {
    select.value = next;
  }
}

async function refresh() {
  const snapQuery = state.branch ? repoQuery() : repoQuery() + rangeQuery();
  const snap = await api("/api/snapshot?" + snapQuery);
  state.hold = snap.hold;
  state.comments = snap.comments;
  state.hunks = snap.hunks;
  if (!state.branch) {
    state.changes = snap.changes;
    state.base = snap.base || state.base;
    showRange(snap);
  }
  $("hold").textContent = state.hold ? "Holding" : "Hold";
  $("hold").classList.toggle("is-holding", state.hold);
  $("hold").setAttribute("aria-pressed", state.hold ? "true" : "false");
  renderSidebar();
  const signature = JSON.stringify({
    comments: state.comments,
    hunks: state.hunks,
  });
  const commentsChanged = signature !== state.viewSignature;
  if (!state.file || state.dirty || state.editing) {
    state.viewSignature = signature;
    return;
  }
  const current = state.changes.find((item) => item.path === state.file.path);
  if (!state.branch && current && current.hash && current.hash !== state.file.hash) {
    await openPath(state.file.path, state.selectedLine, false);
    state.viewSignature = signature;
    return;
  }
  if (commentsChanged) {
    const scroller = $("code");
    const top = scroller.scrollTop;
    renderFile();
    scroller.scrollTop = top;
  }
  state.viewSignature = signature;
}

function renderSidebar() {
  const list = $("file-list");
  list.replaceChildren();
  const rows = state.branch ? state.branchMeta.files : state.changes;
  if (!rows.length) {
    const empty = state.branch
      ? MATCHES_BRANCH + state.branchMeta.baseLabel + "."
      : MATCHES_BASE + state.base + ".";
    list.append(el("li", "meta", empty));
    return;
  }
  rows.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = state.file && state.file.path === item.path ? "active" : "";
    button.title = item.path;
    const count = state.comments.filter((comment) => comment.path === item.path).length;
    if (item.status) {
      const status = document.createElement("span");
      status.className = "status status-" + item.status;
      status.textContent = item.status;
      button.append(status);
    }
    const name = document.createElement("span");
    name.className = "file-name";
    name.textContent = item.path;
    button.append(name);
    if (count) {
      const mark = document.createElement("span");
      mark.className = "count";
      mark.textContent = String(count);
      button.append(mark);
    }
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
  if (!state.file || state.file.path !== path) {
    state.draft = null;
  }
  const onBranch = state.branch && state.branchMeta && state.branchMeta.files.some((item) => item.path === path);
  const url = onBranch
    ? "/api/branch/file?" + branchQuery(path)
    : "/api/file?" + repoQuery() + "&path=" + encodeURIComponent(path) + rangeQuery();
  state.file = await api(url);
  state.editing = false;
  state.dirty = false;
  state.selectedLine = line;
  if (line) {
    revealLine(line);
  }
  $("back").disabled = state.stack.length === 0;
  renderFile();
  renderSidebar();
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
  blank.textContent = "—";
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
  updateFileFold(file);
  if (state.editing) {
    $("editor").value = file.content;
    return;
  }
  const typing = document.activeElement && document.activeElement.classList.contains("draft-body");
  captureDraft();
  const code = $("code");
  code.replaceChildren();
  code.classList.remove("split");
  if (file.binary) {
    code.append(el("p", "empty", "Binary file. Kensa leaves it closed."));
    return;
  }
  const pairs = file.pairs || [];
  if (!pairs.length) {
    code.append(el("p", "empty", "This file is empty."));
    return;
  }
  code.classList.add("split");
  const head = document.createElement("div");
  head.className = "split-head";
  head.append(el("span", "pane-label", "Old"), el("span", "pane-label new", "New"));
  code.append(head);
  const commentsAt = {};
  const orphaned = [];
  state.comments.filter((item) => item.path === file.path).forEach((item) => {
    if (item.orphaned) {
      orphaned.push(item);
      return;
    }
    (commentsAt[item.line] = commentsAt[item.line] || []).push(item);
  });
  if (orphaned.length) {
    code.append(lineThread(orphaned, null, false));
  }
  const commentOnOld = file.status === "D";
  const draftLine = state.draft ? state.draft.line : null;
  let drafted = false;
  visibleRuns(pairs, commentsAt, draftLine, commentOnOld, fileShowsFull(file)).forEach((run) => {
    if (run.type === "fold") {
      code.append(foldRow(run.count, run.line));
      return;
    }
    run.pairs.forEach((pair) => {
      const number = pairLine(pair, commentOnOld);
      code.append(paneCell(PANE_OLD, pair, commentsAt, number, commentOnOld));
      code.append(paneCell(PANE_NEW, pair, commentsAt, number, !commentOnOld));
      if (number == null) {
        return;
      }
      const notes = commentsAt[number] || [];
      const drafting = draftLine === number;
      if (drafting) {
        drafted = true;
      }
      if (notes.length || drafting) {
        code.append(lineThread(notes, number, drafting));
      }
    });
  });
  if (state.draft && !drafted) {
    code.append(lineThread([], state.draft.line, true));
  }
  if (typing && state.draft) {
    const field = document.querySelector(".draft-body");
    if (field) {
      field.focus();
      const end = field.value.length;
      field.setSelectionRange(end, end);
    }
  }
}

function fileShowsFull(file) {
  if (!file || file.status === "context" || file.inReview === false) {
    return true;
  }
  return Boolean(state.fullFiles[file.path]);
}

function pairLine(pair, commentOnOld) {
  return commentOnOld ? pair.oldNum : pair.newNum;
}

function pairStays(pair, commentsAt, draftLine, commentOnOld) {
  if (pair.kind !== PAIR_CONTEXT) {
    return true;
  }
  const line = pairLine(pair, commentOnOld);
  if (line == null) {
    return false;
  }
  if (line === draftLine) {
    return true;
  }
  return Boolean(commentsAt[line] && commentsAt[line].length);
}

function visibleRuns(pairs, commentsAt, draftLine, commentOnOld, expanded) {
  if (expanded) {
    return [{ type: "lines", pairs: pairs }];
  }
  const runs = [];
  let hidden = 0;
  let hiddenLine = null;
  let current = null;
  function flushHidden() {
    if (!hidden) {
      return;
    }
    runs.push({ type: "fold", count: hidden, line: hiddenLine });
    hidden = 0;
    hiddenLine = null;
  }
  pairs.forEach((pair) => {
    if (pairStays(pair, commentsAt, draftLine, commentOnOld)) {
      flushHidden();
      if (!current) {
        current = { type: "lines", pairs: [] };
        runs.push(current);
      }
      current.pairs.push(pair);
      return;
    }
    current = null;
    hidden += 1;
    if (hiddenLine == null) {
      hiddenLine = pairLine(pair, commentOnOld);
    }
  });
  flushHidden();
  return runs;
}

function fileCanFold(file) {
  const pairs = (file && file.pairs) || [];
  let changed = false;
  let context = false;
  pairs.forEach((pair) => {
    if (pair.kind === PAIR_CONTEXT) {
      context = true;
    } else {
      changed = true;
    }
  });
  return changed && context;
}

function updateFileFold(file) {
  const fold = $("file-fold");
  const show = !state.editing && fileCanFold(file);
  fold.hidden = !show;
  if (!show) {
    return;
  }
  const full = fileShowsFull(file);
  fold.textContent = full ? SHOW_CHANGES : SHOW_FULL_FILE;
  fold.setAttribute("aria-expanded", full ? "true" : "false");
}

function revealLine(line) {
  if (!state.file || !line || fileShowsFull(state.file)) {
    return false;
  }
  const commentOnOld = state.file.status === "D";
  const pair = (state.file.pairs || []).find((item) => pairLine(item, commentOnOld) === line);
  if (!pair || pair.kind !== PAIR_CONTEXT) {
    return false;
  }
  state.fullFiles[state.file.path] = true;
  return true;
}

function expandOpenFile(anchorLine) {
  if (!state.file) {
    return;
  }
  state.fullFiles[state.file.path] = true;
  renderFile();
  if (!anchorLine) {
    return;
  }
  const node = document.getElementById("line-" + anchorLine);
  if (node) {
    node.scrollIntoView({ block: "center" });
  }
}

function foldRow(count, anchorLine) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "fold";
  button.textContent = count + (count === 1 ? LINE_HIDDEN : LINES_HIDDEN);
  button.addEventListener("click", () => expandOpenFile(anchorLine));
  return button;
}

function paneCell(side, pair, commentsAt, commentLine, ownsComment) {
  const number = side === PANE_OLD ? pair.oldNum : pair.newNum;
  const text = side === PANE_OLD ? pair.oldText : pair.newText;
  const cell = document.createElement("div");
  const present = text !== null && text !== undefined;
  let tone = "";
  if (present && side === PANE_OLD && (pair.kind === "del" || pair.kind === "change")) {
    tone = "del";
  }
  if (present && side === PANE_NEW && (pair.kind === "add" || pair.kind === "change")) {
    tone = "add";
  }
  cell.className = "cell " + side + (tone ? " " + tone : "") + (number == null ? " blank" : "");
  const gutter = document.createElement("span");
  gutter.className = "gutter";
  if (ownsComment && number != null) {
    cell.id = "line-" + number;
    if (state.selectedLine === number) {
      cell.classList.add("selected");
    }
    (commentsAt[number] || []).forEach((comment) => {
      const dot = document.createElement("span");
      dot.className = "badge " + comment.severity;
      gutter.append(dot);
    });
  }
  if (commentLine != null && number != null) {
    cell.classList.add("commentable");
    cell.addEventListener("click", (event) => {
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed && cell.contains(selection.anchorNode)) {
        return;
      }
      if (event.target.closest("button")) {
        return;
      }
      openDraft(commentLine);
    });
  }
  if (number != null) {
    gutter.append(document.createTextNode(String(number)));
  }
  const pre = document.createElement("pre");
  pre.className = "text";
  pre.textContent = present ? text : "";
  cell.append(gutter, pre);
  return cell;
}

function lineThread(notes, line, drafting) {
  const thread = document.createElement("div");
  thread.className = "line-thread";
  if (line) {
    thread.setAttribute("aria-label", "Line " + line);
  }
  notes.forEach((comment) => thread.append(noteRow(comment)));
  if (drafting) {
    thread.append(draftForm());
  }
  return thread;
}

function noteRow(comment) {
  const row = document.createElement("div");
  row.className = "line-note " + (comment.severity || "") + (comment.orphaned ? " orphaned" : "");
  const severity = document.createElement("span");
  severity.className = "sev";
  severity.textContent = comment.orphaned ? COMMENT_MOVED : comment.severity;
  const body = document.createElement("p");
  body.textContent = comment.body;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "quiet";
  remove.textContent = COMMENT_DISMISS;
  remove.addEventListener("click", () => dismissComment(comment.id));
  row.append(severity, body, remove);
  return row;
}

function draftForm() {
  const form = document.createElement("form");
  form.className = "draft";
  const field = document.createElement("textarea");
  field.className = "draft-body";
  field.rows = 2;
  field.placeholder = COMMENT_PLACEHOLDER;
  field.setAttribute("aria-label", COMMENT_PLACEHOLDER);
  field.value = state.draft.body;
  const actions = document.createElement("div");
  actions.className = "draft-actions";
  const severity = document.createElement("select");
  severity.className = "draft-severity";
  severity.setAttribute("aria-label", SEVERITY_LABEL);
  SEVERITIES.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    if (name === state.draft.severity) {
      option.selected = true;
    }
    severity.append(option);
  });
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "primary";
  save.textContent = COMMENT_SAVE;
  save.disabled = !state.draft.body.trim();
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "quiet";
  cancel.textContent = COMMENT_CANCEL;
  cancel.addEventListener("click", () => closeDraft());
  severity.addEventListener("change", () => {
    state.draft.severity = severity.value;
  });
  field.addEventListener("input", () => {
    state.draft.body = field.value;
    save.disabled = !field.value.trim();
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDraft();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      saveDraft();
    }
  });
  actions.append(severity, save, cancel);
  form.append(field, actions);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveDraft();
  });
  return form;
}

function captureDraft() {
  if (!state.draft) {
    return;
  }
  const field = document.querySelector(".draft-body");
  const severity = document.querySelector(".draft-severity");
  if (field) {
    state.draft.body = field.value;
  }
  if (severity) {
    state.draft.severity = severity.value;
  }
}

function openDraft(line) {
  captureDraft();
  if (state.draft && state.draft.line === line && !state.draft.body.trim()) {
    state.draft = null;
    state.selectedLine = line;
    renderFile();
    return;
  }
  const body = state.draft ? state.draft.body : "";
  const severity = state.draft && SEVERITIES.includes(state.draft.severity)
    ? state.draft.severity
    : SEVERITY_SUGGESTION;
  state.draft = { line: line, severity: severity, body: body };
  state.selectedLine = line;
  renderFile();
  const field = document.querySelector(".draft-body");
  if (field) {
    field.focus();
    const thread = field.closest(".line-thread");
    if (thread) {
      thread.scrollIntoView({ block: "nearest" });
    }
  }
}

function closeDraft() {
  state.draft = null;
  renderFile();
}

function saveDraft() {
  captureDraft();
  if (!state.file || !state.draft || !state.draft.body.trim()) {
    return;
  }
  const line = state.draft.line;
  const severity = state.draft.severity;
  const body = state.draft.body.trim();
  post("/api/comments", {
    path: state.file.path,
    line: line,
    severity: severity,
    body: body,
  }).then(async () => {
    state.draft = null;
    state.selectedLine = line;
    notice("");
    await refresh();
    const node = document.getElementById("line-" + line);
    if (node) {
      node.scrollIntoView({ block: "nearest" });
    }
  }).catch((error) => notice(error.message));
}

function dismissComment(commentId) {
  api("/api/comments?" + repoQuery() + "&id=" + encodeURIComponent(commentId), { method: "DELETE" })
    .then(() => refresh())
    .catch((error) => notice(error.message));
}

function selectLine(line) {
  state.selectedLine = line;
  if (revealLine(line)) {
    renderFile();
    return;
  }
  document.querySelectorAll(".cell.selected").forEach((node) => node.classList.remove("selected"));
  const node = document.getElementById("line-" + line);
  if (node) {
    node.classList.add("selected");
  }
}

function readTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === THEME_BRIGHT || stored === THEME_DARK) {
      return stored;
    }
  } catch (error) {
    return THEME_DARK;
  }
  return THEME_DARK;
}

function applyTheme(theme) {
  const chosen = theme === THEME_BRIGHT ? THEME_BRIGHT : THEME_DARK;
  document.documentElement.setAttribute("data-theme", chosen);
  const toggle = $("theme-toggle");
  const dark = chosen === THEME_DARK;
  toggle.setAttribute("aria-pressed", dark ? "true" : "false");
  const label = dark ? THEME_BRIGHT_LABEL : THEME_DARK_LABEL;
  toggle.setAttribute("aria-label", label);
  toggle.title = label;
  try {
    localStorage.setItem(THEME_KEY, chosen);
  } catch (error) {
    return;
  }
}

function readSidebarCollapsed() {
  try {
    return sessionStorage.getItem(SIDEBAR_KEY) === "1";
  } catch (error) {
    return false;
  }
}

function setSidebarCollapsed(collapsed) {
  $("app").classList.toggle("sidebar-collapsed", collapsed);
  $("sidebar-body").hidden = collapsed;
  const toggle = $("sidebar-toggle");
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  const label = collapsed ? SIDEBAR_SHOW_LABEL : SIDEBAR_HIDE_LABEL;
  toggle.setAttribute("aria-label", label);
  toggle.title = label;
  try {
    sessionStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  } catch (error) {
    return;
  }
}

function bind() {
  $("sidebar-toggle").addEventListener("click", () => {
    setSidebarCollapsed(!$("sidebar-body").hidden);
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
      } else if (state.draft) {
        saveDraft();
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

  $("file-fold").addEventListener("click", () => {
    if (!state.file) {
      return;
    }
    const path = state.file.path;
    if (state.fullFiles[path]) {
      delete state.fullFiles[path];
    } else {
      state.fullFiles[path] = true;
    }
    renderFile();
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

  $("commit-select").addEventListener("change", () => {
    const value = $("commit-select").value;
    if (value === SCOPE_ALL) {
      state.commitChoice = "";
      state.scope = SCOPE_ALL;
    } else {
      state.commitChoice = value;
      state.scope = "";
    }
    reloadReview().catch((error) => notice(error.message));
  });

  $("submit-pr").addEventListener("click", () => {
    const payload = {
      name: state.branch,
      verdict: $("verdict").value,
      summary: $("summary").value,
    };
    if (state.oneOffBase) {
      payload.base = state.oneOffBase;
    }
    post("/api/branch/submit", payload).then((result) => {
      notice("Submitted " + result.inline + " inline comments. " + (result.url || ""));
    }).catch((error) => notice(error.message));
  });
}

async function reloadReview() {
  if (state.branch) {
    state.branchMeta = await api("/api/branch?" + branchQuery());
    showRange(state.branchMeta);
  }
  await refresh();
  const rows = state.branch ? state.branchMeta.files : state.changes;
  const still = state.file && rows.some((item) => item.path === state.file.path);
  if (still) {
    await openPath(state.file.path, state.selectedLine, false);
    return;
  }
  if (rows[0]) {
    await openPath(rows[0].path, null, false);
    return;
  }
  state.file = null;
  const against = state.branch ? (state.branchMeta && state.branchMeta.baseLabel) || "" : state.base || "";
  $("code").replaceChildren();
  $("code").append(el("p", "empty", NO_CHANGES_AGAINST + against + "."));
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
