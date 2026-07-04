const API = "";
const STORAGE_KEY = "assistant_current_user";

const state = {
  tasksFilter: "open",
  notesFilter: "all",
  memoryFilter: "active",
  auditFilter: "actions",
  activeTab: "tasks",
  users: [],
  canEditUsers: false,
};

const ACTION_LABELS = {
  capture: "Создание элемента",
  MEMORY_EXTRACT: "Извлечение памяти",
  "GET /memory": "Запрос памяти",
  "POST /memory": "Добавление в память",
  "PATCH /memory/{id}": "Редактирование памяти",
  "POST /memory/{id}/deactivate": "Отключение факта памяти",
  "DELETE /memory/{id}": "Удаление факта памяти",
  ai_structure: "ИИ-структурирование",
  task_done: "Отметка выполненной",
  patch_task: "Редактирование задачи",
  patch_note: "Редактирование заметки",
  reclassify_item: "Смена типа (задача/заметка)",
  delete_task: "Удаление задачи",
  delete_note: "Удаление заметки",
  get_tasks: "Запрос списка задач",
  get_notes: "Запрос списка заметок",
  get_inbox: "Запрос входящих",
  get_audit: "Запрос журнала",
  get_item: "Открытие карточки",
  get_tags: "Запрос тегов",
  list_users: "Список пользователей",
  create_user: "Создание пользователя",
  patch_user: "Редактирование пользователя",
  reset_database: "Очистка базы",
};

function getUserId() {
  return document.getElementById("currentUserSelect").value || "u_1";
}

function setUserId(id) {
  localStorage.setItem(STORAGE_KEY, id);
  document.getElementById("currentUserSelect").value = id;
  updateCurrentUserInfo();
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function escapeHtml(str) {
  if (str == null) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

function renderTags(tags) {
  if (!tags || !tags.length) return "";
  return `<div class="tags">${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>`;
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

function formatAuditJson(raw) {
  if (!raw) return "—";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function renderAuditCard(r, compact = false) {
  const statusCls = r.status === "error" ? "audit-status-error" : "audit-status-ok";
  const itemLink =
    r.item_type && r.item_id
      ? `<span class="audit-meta-item">${escapeHtml(r.item_type)} · ${escapeHtml(r.item_id)}</span>`
      : "";

  const inputBlock = r.input
    ? `<div class="audit-block">
        <div class="audit-block-label">Вход (input)</div>
        <pre class="audit-json">${escapeHtml(formatAuditJson(r.input))}</pre>
      </div>`
    : "";

  const outputBlock = r.output
    ? `<div class="audit-block">
        <div class="audit-block-label">Ответ (output)</div>
        <pre class="audit-json">${escapeHtml(formatAuditJson(r.output))}</pre>
      </div>`
    : "";

  if (compact) {
    return `
      <div class="audit-card ${r.error ? "has-error" : ""}">
        <div class="audit-header">
          <strong>${escapeHtml(actionLabel(r.action))}</strong>
          <span>${escapeHtml(r.created_at)}</span>
          ${r.error ? `<span class="status-badge review">${escapeHtml(r.error)}</span>` : ""}
        </div>
        ${inputBlock}
        ${outputBlock}
      </div>`;
  }

  return `
    <div class="audit-card ${r.error ? "has-error" : ""} ${r.status === "error" ? "status-error" : ""}">
      <div class="audit-header">
        <strong class="audit-action">${escapeHtml(actionLabel(r.action))}</strong>
        <span class="audit-meta ${statusCls}">${r.status === "error" ? "ошибка" : "ok"}</span>
        <span class="audit-meta">${escapeHtml(r.created_at)}</span>
        <span class="audit-meta">${r.duration_ms} ms</span>
        ${r.error ? `<span class="status-badge review">${escapeHtml(r.error)}</span>` : ""}
      </div>
      <div class="audit-subheader">
        <span class="audit-meta">action: ${escapeHtml(r.action)}</span>
        ${itemLink}
      </div>
      ${inputBlock}
      ${outputBlock}
    </div>`;
}

function priorityXp(priority) {
  const map = {
    high: { cls: "xp-high", label: "высокий" },
    medium: { cls: "xp-medium", label: "средний" },
    low: { cls: "xp-low", label: "низкий" },
  };
  const p = map[priority] || map.medium;
  return `<span class="xp-badge ${p.cls}">${p.label}</span>`;
}

function renderDeleteButton(itemType, itemId, canDelete, blockReason) {
  if (canDelete) {
    return `<button type="button" class="btn btn-delete" onclick="deleteItem('${itemType}', '${itemId}')">Удалить</button>`;
  }
  return `<button type="button" class="btn btn-delete disabled" disabled title="${escapeHtml(blockReason)}">${escapeHtml(blockReason)}</button>`;
}

function buildCard({
  id,
  itemType,
  title,
  preview,
  tags,
  createdAt,
  priority,
  status,
  needsReview,
  onOpen,
  onDone,
}) {
  const isTask = itemType === "task";
  const isDone = status === "done";
  let cardClass = isTask ? "card-task" : "card-note";
  if (isDone) cardClass = "card-done";
  if (needsReview) cardClass += " card-review";

  let statusBadge = "";
  if (isTask) {
    statusBadge = isDone
      ? '<span class="status-badge done">✓ Выполнено</span>'
      : '<span class="status-badge progress">🔥 В процессе</span>';
  } else {
    statusBadge = '<span class="status-badge note">📝 Заметка</span>';
  }
  if (needsReview) {
    statusBadge += ' <span class="status-badge review">⚠ проверка</span>';
  }

  const xp = isTask && priority ? priorityXp(priority) : (isTask ? priorityXp("medium") : "");

  let actionBtn = `<button class="btn btn-open" onclick="openItem('${itemType}', '${id}')">Открыть</button>`;
  if (isTask) {
    if (isDone) {
      actionBtn += '<button class="btn btn-done completed" disabled>✓ Выполнено</button>';
    } else if (needsReview) {
      actionBtn +=
        '<button class="btn btn-done completed" disabled title="Сначала проверьте задачу">⚠ Требует проверки</button>';
    } else if (onDone) {
      actionBtn += `<button class="btn btn-done" onclick="markDone('${id}')">Отметить выполненным</button>`;
    }
  }

  return `
    <article class="item-card ${cardClass}">
      <div class="card-header">
        <div>${statusBadge}</div>
        ${xp}
      </div>
      <h3 class="card-title">${escapeHtml(title)}</h3>
      <p class="card-preview">${escapeHtml(preview)}</p>
      ${renderTags(tags)}
      <div class="card-footer">
        <div class="card-date">${escapeHtml(createdAt)}</div>
        ${actionBtn}
      </div>
    </article>`;
}

function buildUserCard(user, canEdit) {
  const isService = user.role === "service";
  return `
    <article class="item-card user-card ${isService ? "service card-task" : "card-note"}">
      <div class="card-header">
        <span class="status-badge ${isService ? "progress" : "note"}">${isService ? "⚙ служебный" : "👤 пользователь"}</span>
      </div>
      <h3 class="card-title">${escapeHtml(user.full_name || user.id)}</h3>
      <span class="user-position">${escapeHtml(user.position || "—")}</span>
      <div class="user-id-label">ID: ${escapeHtml(user.id)}</div>
      <div class="card-footer">
        ${canEdit && !isService ? `<button class="btn btn-open" onclick="editUser('${user.id}')">Редактировать</button>` : ""}
        ${canEdit && isService ? `<button class="btn btn-open" style="opacity:0.6" disabled>Служебная учётная запись</button>` : ""}
        ${!canEdit ? `<button class="btn btn-open" onclick="switchToUser('${user.id}')">Выбрать</button>` : ""}
      </div>
    </article>`;
}

// --- Users ---

async function loadUsersList() {
  try {
    const data = await apiFetch(`/users?actor_id=${encodeURIComponent(getUserId())}`);
    state.users = data.users;
    state.canEditUsers = data.can_edit;
    populateUserSelect(data.users);
    updateCurrentUserInfo();
    renderUsersTab();
  } catch (e) {
    console.error(e);
  }
}

function populateUserSelect(users) {
  const select = document.getElementById("currentUserSelect");
  const saved = localStorage.getItem(STORAGE_KEY) || "u_1";
  select.innerHTML = users
    .map(
      (u) =>
        `<option value="${escapeHtml(u.id)}">${escapeHtml(u.full_name || u.id)} — ${escapeHtml(u.position || "")}</option>`
    )
    .join("");
  if (users.some((u) => u.id === saved)) {
    select.value = saved;
  }
}

function updateCurrentUserInfo() {
  const user = state.users.find((u) => u.id === getUserId());
  const el = document.getElementById("currentUserInfo");
  if (!user) {
    el.textContent = "";
    return;
  }
  const roleLabel = user.role === "service" ? " · служебный доступ" : "";
  el.textContent = `${user.full_name || user.id} · ${user.position || "—"}${roleLabel}`;
}

function switchToUser(userId) {
  setUserId(userId);
  refreshCurrentTab();
}

function renderUsersTab() {
  const admin = document.getElementById("usersAdminPanel");
  const list = document.getElementById("usersList");

  if (state.canEditUsers) {
    admin.classList.remove("hidden");
    admin.innerHTML = `
      <h3>Добавить пользователя</h3>
      <div class="form-row">
        <input id="newUserId" placeholder="ID (например u_2)">
        <input id="newUserName" placeholder="ФИО">
        <input id="newUserPosition" placeholder="Должность">
      </div>
      <button class="btn btn-gradient-secondary" onclick="createUser()">Создать</button>
    `;
  } else {
    admin.classList.add("hidden");
    admin.innerHTML = `<div class="readonly-notice">Список доступен только для просмотра. Редактирование — у служебного пользователя.</div>`;
    admin.classList.remove("hidden");
  }

  if (!state.users.length) {
    list.innerHTML = '<div class="empty-state">Нет пользователей</div>';
    return;
  }
  list.innerHTML = state.users.map((u) => buildUserCard(u, state.canEditUsers)).join("");
}

async function createUser() {
  const id = document.getElementById("newUserId").value.trim();
  const full_name = document.getElementById("newUserName").value.trim();
  const position = document.getElementById("newUserPosition").value.trim();
  if (!id || !full_name || !position) {
    alert("Заполните ID, ФИО и должность");
    return;
  }
  try {
    await apiFetch("/users", {
      method: "POST",
      body: JSON.stringify({ actor_id: getUserId(), id, full_name, position }),
    });
    await loadUsersList();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function editUser(userId) {
  const user = state.users.find((u) => u.id === userId);
  if (!user) return;
  openModal(`
    <div class="modal-header">
      <h3>Редактировать пользователя</h3>
      <p>${escapeHtml(user.id)}</p>
    </div>
    <div class="modal-body">
      <div class="detail-field"><label>ФИО</label><input id="editUserName" value="${escapeHtml(user.full_name || "")}"></div>
      <div class="detail-field"><label>Должность</label><input id="editUserPosition" value="${escapeHtml(user.position || "")}"></div>
      <button class="btn btn-gradient-secondary" onclick="saveUser('${userId}')">Сохранить</button>
    </div>
  `);
}

async function saveUser(userId) {
  try {
    await apiFetch(`/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({
        actor_id: getUserId(),
        full_name: document.getElementById("editUserName").value,
        position: document.getElementById("editUserPosition").value,
      }),
    });
    closeModal();
    await loadUsersList();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

// --- Capture ---

function renderCaptureSummary(data) {
  const items = data.items || [];
  if (!items.length) {
    return "<strong>Ничего не распознано.</strong> Попробуйте сформулировать конкретнее.";
  }
  const head = data.duplicate
    ? `<strong>Уже было добавлено (${items.length}):</strong>`
    : `<strong>Распознано и создано: ${items.length}</strong>`;
  const rows = items
    .map((it) => {
      const kind = it.item_type === "task" ? "Задача" : "Заметка";
      const review = it.needs_review ? " · ⚠ требует проверки" : "";
      return `<div class="capture-item">• ${kind}: ${escapeHtml(it.title)}${review}</div>`;
    })
    .join("");
  const ignored =
    data.ignored && data.ignored.trim()
      ? `<div class="capture-ignored">Отброшено как несущественное: ${escapeHtml(data.ignored)}</div>`
      : "";

  let memoryLine = "";
  const mem = data.memory;
  if (mem) {
    if (mem.created > 0 && mem.needs_review > 0) {
      memoryLine = `<div class="capture-memory">Память: добавлено ${mem.created} факт(ов), ${mem.needs_review} — проверьте «Память → Требует проверки»</div>`;
    } else if (mem.created > 0) {
      memoryLine = `<div class="capture-memory">Память: добавлено ${mem.created} факт(ов)</div>`;
    } else if (mem.skipped > 0) {
      memoryLine = `<div class="capture-memory">Память: новых фактов нет (уже сохранено). Смотрите вкладку «Память».</div>`;
    } else {
      memoryLine = `<div class="capture-memory">Память: подходящих фактов не найдено</div>`;
    }
    if (data.duplicate) {
      memoryLine += `<div class="capture-memory-hint">Текст уже обрабатывался; память проверена повторно.</div>`;
    }
  }

  return `${head}${rows}${ignored}${memoryLine}`;
}

document.getElementById("captureBtn").addEventListener("click", async () => {
  const text = document.getElementById("captureText").value.trim();
  const resultEl = document.getElementById("captureResult");
  if (!text) {
    resultEl.className = "capture-result";
    resultEl.textContent = "Введите текст.";
    resultEl.classList.remove("hidden");
    return;
  }
  try {
    const data = await apiFetch("/capture", {
      method: "POST",
      body: JSON.stringify({ text, user_id: getUserId() }),
    });
    resultEl.className = "capture-result success";
    resultEl.innerHTML = renderCaptureSummary(data);
    resultEl.classList.remove("hidden");
    document.getElementById("captureText").value = "";
    refreshCurrentTab();
  } catch (e) {
    resultEl.className = "capture-result";
    resultEl.textContent = `Ошибка: ${e.message}`;
    resultEl.classList.remove("hidden");
  }
});

document.getElementById("resetBtn").addEventListener("click", async () => {
  if (!confirm("Удалить все задачи, заметки и журнал?\nПользователи будут восстановлены по умолчанию.")) return;
  try {
    const data = await apiFetch("/reset", { method: "POST", body: "{}" });
    document.getElementById("captureResult").className = "capture-result success";
    document.getElementById("captureResult").textContent = data.message;
    document.getElementById("captureResult").classList.remove("hidden");
    closeModal();
    await loadUsersList();
    refreshCurrentTab();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
});

document.getElementById("currentUserSelect").addEventListener("change", () => {
  setUserId(getUserId());
  loadUsersList();
  refreshCurrentTab();
});

// --- Tabs ---

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    state.activeTab = tab.dataset.tab;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(`tab-${state.activeTab}`).classList.remove("hidden");
    refreshCurrentTab();
  });
});

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const panel = btn.dataset.panel;
    document.querySelectorAll(`.filter-btn[data-panel="${panel}"]`).forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    if (panel === "notes") state.notesFilter = btn.dataset.filter;
    if (panel === "tasks") state.tasksFilter = btn.dataset.filter;
    if (panel === "memory") state.memoryFilter = btn.dataset.filter;
    if (panel === "audit") state.auditFilter = btn.dataset.filter;
    refreshCurrentTab();
  });
});

function refreshCurrentTab() {
  if (state.activeTab === "tasks") loadTasks();
  if (state.activeTab === "notes") loadNotes();
  if (state.activeTab === "memory") loadMemory();
  if (state.activeTab === "audit") loadAudit();
  if (state.activeTab === "users") loadUsersList();
}

async function loadNotes() {
  const list = document.getElementById("notesList");
  let url = `/notes?user_id=${encodeURIComponent(getUserId())}`;
  if (state.notesFilter === "review") url += "&needs_review=true";
  try {
    const notes = await apiFetch(url);
    if (!notes.length) {
      list.innerHTML = '<div class="empty-state">Нет заметок</div>';
      return;
    }
    list.innerHTML = notes
      .map((n) =>
        buildCard({
          id: n.id,
          itemType: "note",
          title: n.title,
          preview: n.preview,
          tags: n.tags,
          createdAt: n.created_at,
          needsReview: n.needs_review,
        })
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

const MEMORY_CATEGORY_LABELS = {
  preference: "предпочтение",
  context: "контекст",
  habit: "привычка",
  project: "проект",
  person: "человек",
  other: "другое",
};

function renderMemoryCard(f) {
  const badges = [];
  if (f.needs_review) badges.push('<span class="status-badge review">требует проверки</span>');
  if (!f.is_active) badges.push('<span class="status-badge inactive">отключено</span>');
  return `
    <article class="memory-card ${f.needs_review ? "memory-review" : ""} ${!f.is_active ? "memory-inactive" : ""}">
      <div class="memory-card-header">
        <strong>${escapeHtml(f.key)}</strong>
        <span class="memory-meta">${escapeHtml(MEMORY_CATEGORY_LABELS[f.category] || f.category)} · ${escapeHtml(f.confidence)}</span>
      </div>
      <div class="memory-value">${escapeHtml(f.value)}</div>
      <div class="memory-footer">
        <span class="memory-source">${escapeHtml(f.source_type || "—")} · ${escapeHtml(f.created_at)}</span>
        <div class="memory-badges">${badges.join(" ")}</div>
      </div>
      <div class="memory-actions">
        <button type="button" class="btn btn-open" onclick="editMemory('${f.id}')">Редактировать</button>
        ${f.is_active ? `<button type="button" class="btn btn-ghost" onclick="deactivateMemory('${f.id}')">Отключить</button>` : ""}
        <button type="button" class="btn btn-delete" onclick="deleteMemory('${f.id}')">Удалить</button>
      </div>
    </article>`;
}

async function loadMemory() {
  const list = document.getElementById("memoryList");
  let url = `/memory?user_id=${encodeURIComponent(getUserId())}`;
  if (state.memoryFilter === "active") {
    url += "&include_inactive=false";
  } else if (state.memoryFilter === "review") {
    url += "&include_inactive=true&needs_review=true";
  } else {
    url += "&include_inactive=true";
  }
  try {
    const facts = await apiFetch(url);
    if (!facts.length) {
      list.innerHTML = '<div class="empty-state">Нет сохранённых фактов памяти</div>';
      return;
    }
    list.innerHTML = facts.map(renderMemoryCard).join("");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

async function addMemoryFact() {
  const key = document.getElementById("memoryKey").value.trim();
  const value = document.getElementById("memoryValue").value.trim();
  const category = document.getElementById("memoryCategory").value;
  if (!key || value.length < 3) {
    alert("Укажите key и value (минимум 3 символа).");
    return;
  }
  try {
    await apiFetch("/memory", {
      method: "POST",
      body: JSON.stringify({ user_id: getUserId(), key, value, category }),
    });
    document.getElementById("memoryKey").value = "";
    document.getElementById("memoryValue").value = "";
    loadMemory();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function editMemory(id) {
  try {
    const facts = await apiFetch(`/memory?user_id=${encodeURIComponent(getUserId())}&include_inactive=true`);
    const fact = facts.find((f) => f.id === id);
    if (!fact) {
      alert("Факт не найден");
      return;
    }
    const categoryOptions = ["preference", "context", "habit", "project", "person", "other"]
      .map(
        (c) =>
          `<option value="${c}" ${fact.category === c ? "selected" : ""}>${escapeHtml(MEMORY_CATEGORY_LABELS[c] || c)}</option>`
      )
      .join("");

    openModal(`
      <div class="modal-header modal-header-memory">
        <h3>Память</h3>
        <p>${escapeHtml(fact.value)}</p>
      </div>
      <div class="modal-body">
        <div class="detail-field">
          <label for="editMemKey">Ключ</label>
          <input id="editMemKey" type="text" value="${escapeHtml(fact.key)}" />
          <span class="field-hint">Техническое имя правила</span>
        </div>
        <div class="detail-field">
          <label for="editMemValue">Значение</label>
          <textarea id="editMemValue" rows="3">${escapeHtml(fact.value)}</textarea>
          <span class="field-hint">Как это правило должно применяться</span>
        </div>
        <div class="detail-field">
          <label for="editMemCategory">Категория</label>
          <select id="editMemCategory">${categoryOptions}</select>
        </div>
        <div class="detail-fields-inline">
          <div class="detail-field detail-field-check">
            <label class="check-label" for="editMemReview">
              <input type="checkbox" id="editMemReview" ${fact.needs_review ? "checked" : ""} />
              <span>Требует проверки</span>
            </label>
          </div>
          <div class="detail-field detail-field-check">
            <label class="check-label" for="editMemActive">
              <input type="checkbox" id="editMemActive" ${fact.is_active ? "checked" : ""} />
              <span>Активен</span>
            </label>
          </div>
        </div>
        <div class="modal-actions modal-actions-center">
          <button type="button" class="btn btn-gradient-secondary" onclick="saveMemory('${id}')">Сохранить</button>
        </div>
      </div>`);
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function saveMemory(id) {
  try {
    await apiFetch(`/memory/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        user_id: getUserId(),
        key: document.getElementById("editMemKey").value.trim(),
        value: document.getElementById("editMemValue").value.trim(),
        category: document.getElementById("editMemCategory").value,
        needs_review: document.getElementById("editMemReview").checked,
        is_active: document.getElementById("editMemActive").checked,
      }),
    });
    closeModal();
    loadMemory();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function deactivateMemory(id) {
  if (!confirm("Отключить этот факт? Он перестанет использоваться в ИИ-контексте.")) return;
  try {
    await apiFetch(`/memory/${id}/deactivate`, {
      method: "POST",
      body: JSON.stringify({ user_id: getUserId() }),
    });
    loadMemory();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function deleteMemory(id) {
  if (!confirm("Удалить факт памяти безвозвратно?")) return;
  try {
    await apiFetch(`/memory/${id}?user_id=${encodeURIComponent(getUserId())}`, { method: "DELETE" });
    loadMemory();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

document.getElementById("memoryAddBtn").addEventListener("click", addMemoryFact);

async function loadTasks() {
  const list = document.getElementById("tasksList");
  let url = `/tasks?user_id=${encodeURIComponent(getUserId())}`;
  if (state.tasksFilter === "open" || state.tasksFilter === "done") {
    url += `&status=${state.tasksFilter}`;
  }
  if (state.tasksFilter === "review") url += "&needs_review=true";
  try {
    const tasks = await apiFetch(url);
    if (!tasks.length) {
      list.innerHTML = '<div class="empty-state">Нет задач</div>';
      return;
    }
    list.innerHTML = tasks
      .map((t) =>
        buildCard({
          id: t.id,
          itemType: "task",
          title: t.title,
          preview: t.preview || t.title,
          tags: t.tags,
          createdAt: t.created_at,
          priority: t.priority,
          status: t.status,
          needsReview: t.needs_review,
          onDone: t.status === "open" && !t.needs_review,
        })
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

async function markDone(taskId) {
  try {
    await apiFetch(`/tasks/${taskId}/done`, {
      method: "POST",
      body: JSON.stringify({ user_id: getUserId() }),
    });
    refreshCurrentTab();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function loadAudit() {
  const list = document.getElementById("auditList");
  let url = `/audit?user_id=${encodeURIComponent(getUserId())}&limit=100`;
  if (state.auditFilter === "errors") {
    url += "&only_errors=true&actions_only=false";
  } else if (state.auditFilter === "all") {
    url += "&actions_only=false";
  } else {
    url += "&actions_only=true";
  }
  try {
    const runs = await apiFetch(url);
    if (!runs.length) {
      list.innerHTML = '<div class="empty-state">Нет записей</div>';
      return;
    }
    list.innerHTML = runs.map((r) => renderAuditCard(r)).join("");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

function buildAuditExportUrl(format) {
  let url = `/audit/export?user_id=${encodeURIComponent(getUserId())}&format=${format}&limit=500`;
  if (state.auditFilter === "errors") {
    url += "&only_errors=true&actions_only=false";
  } else if (state.auditFilter === "all") {
    url += "&actions_only=false";
  } else {
    url += "&actions_only=true";
  }
  return url;
}

function buildInboxExportUrl(format) {
  return `/export/inbox?user_id=${encodeURIComponent(getUserId())}&format=${format}&limit=500`;
}

document.querySelectorAll("[data-export]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const kind = btn.dataset.export;
    const format = btn.dataset.format || "json";
    const url =
      kind === "audit" ? buildAuditExportUrl(format) : buildInboxExportUrl(format);
    window.location.href = url;
  });
});

// --- Modal ---

function openModal(html) {
  document.getElementById("modalContent").innerHTML = html;
  document.getElementById("modalOverlay").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modalOverlay").classList.add("hidden");
  document.getElementById("modalContent").innerHTML = "";
}

document.getElementById("closeModal").addEventListener("click", closeModal);
document.getElementById("modalOverlay").addEventListener("click", (e) => {
  if (e.target.id === "modalOverlay") closeModal();
});

function renderItemTypeSelector(currentType) {
  return `
    <div class="detail-field">
      <label for="editItemType">Тип записи</label>
      <select id="editItemType">
        <option value="task" ${currentType === "task" ? "selected" : ""}>Задача</option>
        <option value="note" ${currentType === "note" ? "selected" : ""}>Заметка</option>
      </select>
      <span class="field-hint">Пока элемент требует проверки, можно указать, задача это или заметка</span>
    </div>`;
}

async function openItem(itemType, itemId) {
  try {
    const data = await apiFetch(
      `/items/${itemType}/${itemId}?user_id=${encodeURIComponent(getUserId())}`
    );
    const item = data.item;
    let body = "";

    if (itemType === "task") {
      body = `
        <div class="modal-header">
          <h3>Задача</h3>
          <p>${escapeHtml(item.title)}</p>
        </div>
        <div class="modal-body">
          ${item.needs_review ? renderItemTypeSelector("task") : ""}
          <div class="detail-field"><label>Название</label><input id="editTitle" value="${escapeHtml(item.title)}"></div>
          <div class="detail-field"><label>Описание</label><textarea id="editDescription" placeholder="Подробности задачи">${escapeHtml(item.description || "")}</textarea></div>
          ${
            item.source_text != null
              ? `<div class="detail-field"><label>Исходный текст <span class="field-hint">(сохранён, т.к. задача требует проверки)</span></label><textarea id="editSourceText">${escapeHtml(item.source_text)}</textarea></div>`
              : ""
          }
          <div class="detail-field"><label>Приоритет</label>
            <select id="editPriority">
              <option value="low" ${item.priority === "low" ? "selected" : ""}>low</option>
              <option value="medium" ${item.priority === "medium" ? "selected" : ""}>medium</option>
              <option value="high" ${item.priority === "high" ? "selected" : ""}>high</option>
            </select>
          </div>
          <div class="detail-field">
            <label for="editDueDate">Срок выполнения</label>
            <input type="date" id="editDueDate" value="${item.due_date || ""}">
            <span class="field-hint">Необязательно — выберите дату в календаре</span>
          </div>
          <div class="detail-field"><label>Статус</label><input readonly value="${escapeHtml(item.status)}"></div>
          <div class="detail-field"><label>Теги</label>${renderTags(data.tags)}</div>
          <div class="detail-field detail-field-check">
            <label class="check-label" for="editNeedsReview">
              <input type="checkbox" id="editNeedsReview" ${item.needs_review ? "checked" : ""}>
              <span>Требует проверки</span>
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn btn-gradient-secondary" onclick="saveTask('${item.id}')">Сохранить</button>
            ${renderDeleteButton(
              "task",
              item.id,
              item.status !== "done",
              "Выполненные задачи нельзя удалить"
            )}
          </div>
          ${renderAuditSection(data.audit_runs)}
        </div>`;
    } else {
      body = `
        <div class="modal-header" style="background: var(--grad-note)">
          <h3>Заметка</h3>
          <p>${escapeHtml(item.title)}</p>
        </div>
        <div class="modal-body">
          ${item.needs_review ? renderItemTypeSelector("note") : ""}
          <div class="detail-field"><label>Заголовок</label><input id="editNoteTitle" value="${escapeHtml(item.title)}"></div>
          <div class="detail-field"><label>Содержание</label><textarea id="editText">${escapeHtml(item.text)}</textarea></div>
          ${
            item.source_text != null
              ? `<div class="detail-field"><label>Исходный текст <span class="field-hint">(сохранён, т.к. заметка требует проверки)</span></label><textarea id="editNoteSourceText">${escapeHtml(item.source_text)}</textarea></div>`
              : ""
          }
          <div class="detail-field"><label>Теги</label>${renderTags(data.tags)}</div>
          <div class="detail-field detail-field-check">
            <label class="check-label" for="editNeedsReview">
              <input type="checkbox" id="editNeedsReview" ${item.needs_review ? "checked" : ""}>
              <span>Требует проверки</span>
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn btn-gradient-secondary" onclick="saveNote('${item.id}')">Сохранить</button>
            ${renderDeleteButton(
              "note",
              item.id,
              !item.needs_review,
              "Заметки с проверкой нельзя удалить"
            )}
          </div>
          ${renderAuditSection(data.audit_runs)}
        </div>`;
    }
    openModal(body);
  } catch (e) {
    openModal(`<div class="modal-body"><div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div></div>`);
  }
}

function renderAuditSection(runs) {
  if (!runs || !runs.length) return "";
  return `
    <div class="detail-audit">
      <h4>Журнал по элементу (${runs.length})</h4>
      ${runs.slice(0, 5).map((r) => renderAuditCard(r, true)).join("")}
    </div>`;
}

async function deleteItem(itemType, itemId) {
  const label = itemType === "task" ? "задачу" : "заметку";
  if (!confirm(`Удалить ${label}? Это действие нельзя отменить.`)) return;
  try {
    await apiFetch(`/${itemType}s/${itemId}`, {
      method: "DELETE",
      body: JSON.stringify({ user_id: getUserId() }),
    });
    closeModal();
    refreshCurrentTab();
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function saveTask(taskId) {
  try {
    const targetType = document.getElementById("editItemType")?.value || "task";
    const payload = {
      user_id: getUserId(),
      title: document.getElementById("editTitle").value,
      description: document.getElementById("editDescription").value,
      priority: document.getElementById("editPriority").value,
      due_date: document.getElementById("editDueDate").value || null,
      needs_review: document.getElementById("editNeedsReview").checked,
    };
    const sourceEl = document.getElementById("editSourceText");
    if (sourceEl) payload.source_text = sourceEl.value;

    if (targetType !== "task") {
      payload.target_type = "note";
      payload.text = payload.description || payload.title;
      const data = await apiFetch(`/items/task/${taskId}/reclassify`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      refreshCurrentTab();
      openItem(data.item_type, data.item_id);
      return;
    }

    await apiFetch(`/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    refreshCurrentTab();
    openItem("task", taskId);
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

async function saveNote(noteId) {
  try {
    const targetType = document.getElementById("editItemType")?.value || "note";
    const payload = {
      user_id: getUserId(),
      title: document.getElementById("editNoteTitle").value,
      text: document.getElementById("editText").value,
      needs_review: document.getElementById("editNeedsReview").checked,
    };
    const noteSourceEl = document.getElementById("editNoteSourceText");
    if (noteSourceEl) payload.source_text = noteSourceEl.value;

    if (targetType !== "note") {
      payload.target_type = "task";
      payload.description = payload.text;
      payload.priority = "medium";
      const data = await apiFetch(`/items/note/${noteId}/reclassify`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      refreshCurrentTab();
      openItem(data.item_type, data.item_id);
      return;
    }

    await apiFetch(`/notes/${noteId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    refreshCurrentTab();
    openItem("note", noteId);
  } catch (e) {
    alert(`Ошибка: ${e.message}`);
  }
}

window.deleteItem = deleteItem;
window.openItem = openItem;
window.markDone = markDone;
window.saveTask = saveTask;
window.saveNote = saveNote;
window.createUser = createUser;
window.editUser = editUser;
window.saveUser = saveUser;
window.switchToUser = switchToUser;
window.editMemory = editMemory;
window.saveMemory = saveMemory;
window.deactivateMemory = deactivateMemory;
window.deleteMemory = deleteMemory;

loadUsersList().then(() => loadTasks());
