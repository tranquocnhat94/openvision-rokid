const state = {
  peopleRegistry: null,
  people: [],
  identity: null,
  identityContacts: [],
  selectedPersonId: null,
  peopleFilter: "all",
  peopleSearch: "",
  peopleEditorDirty: false,
  peopleDraft: null,
  peopleRenderSignature: "",
};

let refreshInFlight = false;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function text(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  if (value === null || value === undefined) return "none";
  return String(value);
}

function normalized(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

function setText(parent, selector, value) {
  const node = parent.querySelector(selector);
  if (node) node.textContent = value;
}

function updatePageStatus(error = null) {
  const chip = document.querySelector("#peopleStatusChip");
  if (!chip) return;
  if (error) {
    chip.textContent = "Offline";
    chip.className = "chip error";
    return;
  }
  const registry = state.peopleRegistry;
  chip.textContent = registry?.status || "Checking";
  chip.className = registry?.status === "ready" ? "chip" : registry?.status === "ready_empty" ? "chip muted" : "chip warn";
}

function personContact(person) {
  const names = [person.display_name || "", ...(person.aliases || [])].map(normalized).filter(Boolean);
  return (state.identityContacts || []).find((contact) => {
    const contactNames = [contact.display_name || "", ...(contact.aliases || [])].map(normalized).filter(Boolean);
    return contact.sample_count > 0 && names.some((name) => contactNames.includes(name));
  });
}

function filteredPeople() {
  const query = normalized(state.peopleSearch);
  const filtered = (state.people || []).filter((person) => {
    const enrolled = Boolean(personContact(person));
    const syncStatus = person.sync?.status || "";
    if (state.peopleFilter === "named" && !person.display_name) return false;
    if (state.peopleFilter === "unnamed" && person.display_name) return false;
    if (state.peopleFilter === "enrolled" && !enrolled) return false;
    if (state.peopleFilter === "conflict" && syncStatus !== "name_conflict") return false;
    if (!query) return true;
    const haystack = normalized([
      person.display_name,
      person.person_id,
      person.immich_person_id,
      (person.aliases || []).join(" "),
      person.phone,
      person.address,
      person.age,
      person.where_lives,
      person.relationship,
      person.first_met,
      Object.values(person.facts || {}).join(" "),
      Object.values(person.links || {}).join(" "),
      person.notes,
    ].join(" "));
    return haystack.includes(query);
  });
  return filtered.sort((a, b) => {
    const aNamed = a.display_name ? 0 : 1;
    const bNamed = b.display_name ? 0 : 1;
    if (aNamed !== bNamed) return aNamed - bNamed;
    return String(a.display_name || a.person_id).localeCompare(String(b.display_name || b.person_id));
  });
}

function peopleLinksText(links) {
  return Object.entries(links || {}).map(([key, value]) => `${key}=${value}`).join("\n");
}

function parsePeopleLinks(value) {
  const raw = String(value || "").trim();
  if (!raw) return {};
  if (raw.startsWith("{")) {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  }
  const links = {};
  for (const line of raw.split("\n")) {
    const clean = line.trim();
    if (!clean) continue;
    const index = clean.indexOf("=");
    if (index > 0) {
      links[clean.slice(0, index).trim()] = clean.slice(index + 1).trim();
    } else {
      links[`link${Object.keys(links).length + 1}`] = clean;
    }
  }
  return links;
}

function parsePeopleFacts(value) {
  const raw = String(value || "").trim();
  if (!raw) return {};
  if (raw.startsWith("{")) {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  }
  const facts = {};
  for (const line of raw.split("\n")) {
    const clean = line.trim();
    if (!clean) continue;
    const index = clean.indexOf("=");
    if (index > 0) {
      facts[clean.slice(0, index).trim()] = clean.slice(index + 1).trim();
    } else {
      facts[`fact${Object.keys(facts).length + 1}`] = clean;
    }
  }
  return facts;
}

function peopleFormPayload(syncName = false) {
  return {
    display_name: document.querySelector("#peopleName")?.value || "",
    aliases: (document.querySelector("#peopleAliases")?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    phone: document.querySelector("#peoplePhone")?.value || "",
    address: document.querySelector("#peopleAddress")?.value || "",
    age: document.querySelector("#peopleAge")?.value || "",
    where_lives: document.querySelector("#peopleWhereLives")?.value || "",
    relationship: document.querySelector("#peopleRelationship")?.value || "",
    first_met: document.querySelector("#peopleFirstMet")?.value || "",
    links: parsePeopleLinks(document.querySelector("#peopleLinks")?.value || ""),
    facts: parsePeopleFacts(document.querySelector("#peopleFacts")?.value || ""),
    notes: document.querySelector("#peopleNotes")?.value || "",
    sync_name_to_immich: syncName,
  };
}

function capturePeopleDraft() {
  state.peopleDraft = {
    display_name: document.querySelector("#peopleName")?.value || "",
    aliases: document.querySelector("#peopleAliases")?.value || "",
    phone: document.querySelector("#peoplePhone")?.value || "",
    address: document.querySelector("#peopleAddress")?.value || "",
    age: document.querySelector("#peopleAge")?.value || "",
    where_lives: document.querySelector("#peopleWhereLives")?.value || "",
    relationship: document.querySelector("#peopleRelationship")?.value || "",
    first_met: document.querySelector("#peopleFirstMet")?.value || "",
    links: document.querySelector("#peopleLinks")?.value || "",
    facts: document.querySelector("#peopleFacts")?.value || "",
    notes: document.querySelector("#peopleNotes")?.value || "",
  };
}

function renderFaceThumb(person, sizeClass = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `face-thumb ${sizeClass}`.trim();
  if (person?.thumbnail_ref || person?.immich_thumbnail_ref) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = `/api/people/${encodeURIComponent(person.person_id)}/thumbnail`;
    image.alt = person.display_name || "Immich face";
    image.addEventListener("error", () => {
      const fallback = document.createElement("div");
      fallback.className = "face-thumb-fallback";
      fallback.textContent = (person.display_name || "?").slice(0, 2).toUpperCase();
      image.replaceWith(fallback);
    }, { once: true });
    wrapper.append(image);
  } else {
    const fallback = document.createElement("div");
    fallback.className = "face-thumb-fallback";
    fallback.textContent = (person?.display_name || "?").slice(0, 2).toUpperCase();
    wrapper.append(fallback);
  }
  return wrapper;
}

function renderPeopleRegistry() {
  const root = document.querySelector("#peopleRegistry");
  if (!root) return;
  root.innerHTML = "";
  const registry = state.peopleRegistry;
  const statusClass = registry?.status === "ready" ? "chip" : registry?.status === "ready_empty" ? "chip muted" : "chip warn";
  const immichClass = registry?.immich?.configured ? "chip" : "chip muted";
  const selectedExists = state.people.some((person) => person.person_id === state.selectedPersonId);
  if (!selectedExists) {
    const firstNamed = state.people.find((person) => person.display_name);
    state.selectedPersonId = firstNamed?.person_id || state.people[0]?.person_id || null;
    state.peopleEditorDirty = false;
    state.peopleDraft = null;
  }
  const selected = state.people.find((person) => person.person_id === state.selectedPersonId) || null;
  const people = filteredPeople();
  const signature = JSON.stringify({
    status: registry?.status,
    people: registry?.people_count,
    named: registry?.named_count,
    identity: state.identity?.sample_count,
    selected: state.selectedPersonId,
    selectedUpdatedAt: selected?.updated_at,
    selectedSync: selected?.sync?.status,
    filter: state.peopleFilter,
    search: state.peopleSearch,
    dirty: state.peopleEditorDirty,
    draft: state.peopleDraft,
  });
  if (root.childElementCount && state.peopleRenderSignature === signature) {
    return;
  }
  state.peopleRenderSignature = signature;

  const shell = document.createElement("div");
  shell.className = "people-manager";
  shell.innerHTML = `
    <div class="people-summary">
      <div>
        <div class="item-title">Face / People Registry</div>
        <div class="item-meta"><span class="${statusClass}">${registry?.status || "unknown"}</span> <span class="${immichClass}">Immich ${registry?.immich?.configured ? "configured" : "unconfigured"}</span></div>
        <div class="item-meta">people: ${registry?.people_count ?? 0} · linked Immich: ${registry?.linked_immich_count ?? 0} · named: ${registry?.named_count ?? 0} · identity samples: ${state.identity?.sample_count ?? 0}</div>
        <div class="item-meta">remembered captures: ${registry?.remembered_capture_count ?? 0} · pending face sync: ${registry?.pending_face_sync_count ?? 0}</div>
        <div class="item-meta">images: ${registry?.image_storage || "immich_refs_only"} · last sync: ${registry?.last_sync?.status || "none"}</div>
      </div>
      <div class="people-actions">
        <button id="peopleSyncButton" type="button">Sync Immich</button>
        <button id="peopleRefreshButton" type="button">Refresh</button>
      </div>
    </div>
    <div class="people-toolbar">
      <input id="peopleSearch" type="search" placeholder="Search name, alias, phone, link..." value="">
      <select id="peopleFilter">
        <option value="all">All faces</option>
        <option value="named">Named</option>
        <option value="unnamed">Unnamed</option>
        <option value="enrolled">Identity enrolled</option>
        <option value="conflict">Name conflicts</option>
      </select>
      <span class="chip muted">${people.length} shown</span>
    </div>
    <div class="people-workspace">
      <div class="people-list" id="peopleList"></div>
      <div class="people-editor" id="peopleEditor"></div>
    </div>
  `;
  root.append(shell);

  const search = shell.querySelector("#peopleSearch");
  const filter = shell.querySelector("#peopleFilter");
  search.value = state.peopleSearch;
  filter.value = state.peopleFilter;
  search.addEventListener("input", () => {
    state.peopleSearch = search.value;
    renderPeopleRegistry();
    const nextSearch = document.querySelector("#peopleSearch");
    if (nextSearch) {
      nextSearch.focus();
      nextSearch.setSelectionRange(nextSearch.value.length, nextSearch.value.length);
    }
  });
  filter.addEventListener("change", () => {
    state.peopleFilter = filter.value;
    renderPeopleRegistry();
  });
  shell.querySelector("#peopleSyncButton").addEventListener("click", syncPeopleRegistry);
  shell.querySelector("#peopleRefreshButton").addEventListener("click", refresh);

  const listRoot = shell.querySelector("#peopleList");
  if (!people.length) {
    const empty = document.createElement("article");
    empty.className = "item";
    empty.innerHTML = '<div class="item-title">No matching faces</div><div class="item-meta">Try another search/filter, or sync Immich first.</div>';
    listRoot.append(empty);
  }
  for (const person of people.slice(0, 120)) {
    const enrolled = personContact(person);
    const row = document.createElement("button");
    row.type = "button";
    row.className = `person-card ${person.person_id === state.selectedPersonId ? "selected" : ""}`;
    row.append(renderFaceThumb(person));
    const body = document.createElement("div");
    body.className = "person-card-body";
    body.innerHTML = `
      <div class="person-card-name"></div>
      <div class="item-meta"></div>
      <div class="person-card-chips">
        <span class="chip ${person.display_name ? "" : "muted"}">${person.display_name ? "named" : "unnamed"}</span>
        <span class="chip ${enrolled ? "" : "muted"}">${enrolled ? "identity" : "no sample"}</span>
        <span class="chip ${person.sync?.status === "name_conflict" ? "warn" : "muted"}">${person.sync?.status || "none"}</span>
      </div>
    `;
    setText(body, ".person-card-name", person.display_name || "Unnamed face");
    setText(body, ".item-meta", `${person.person_id} · assets ${person.immich_asset_count ?? 0}`);
    row.append(body);
    row.addEventListener("click", () => selectPerson(person.person_id));
    listRoot.append(row);
  }

  renderPeopleEditor(shell.querySelector("#peopleEditor"), selected);
}

function renderPeopleEditor(root, person) {
  if (!root) return;
  root.innerHTML = "";
  if (!person) {
    root.innerHTML = '<div class="item"><div class="item-title">Select a face</div><div class="item-meta">Pick a face group from the left to edit metadata and enroll identity.</div></div>';
    return;
  }
  const enrolled = personContact(person);
  const conflict = person.sync?.status === "name_conflict" ? person.sync?.conflict : null;
  const editor = document.createElement("article");
  editor.className = "people-editor-card";
  editor.innerHTML = `
    <div class="people-editor-head">
      <div id="peopleEditorThumb"></div>
      <div>
        <div class="item-title" id="peopleEditorTitle"></div>
        <div class="item-meta">${person.person_id}</div>
        <div class="transcript-chips">
          <span>${person.name_source || "none"}</span>
          <span>${enrolled ? `identity samples ${enrolled.sample_count || 0}` : "not enrolled"}</span>
          <span>Immich assets ${person.immich_asset_count ?? 0}</span>
        </div>
      </div>
    </div>
    <div id="peopleConflict"></div>
    <label class="field">Name<input id="peopleName" type="text"></label>
    <label class="field">Aliases comma-separated<input id="peopleAliases" type="text"></label>
    <label class="field">Phone<input id="peoplePhone" type="text"></label>
    <label class="field">Address<input id="peopleAddress" type="text"></label>
    <label class="field">Age / birthday<input id="peopleAge" type="text" placeholder="for example: 32, or born 1994"></label>
    <label class="field">Where lives<input id="peopleWhereLives" type="text"></label>
    <label class="field">Relationship / why known<input id="peopleRelationship" type="text" placeholder="friend, colleague, neighbor..."></label>
    <label class="field">First met<input id="peopleFirstMet" type="text" placeholder="where/when you first met"></label>
    <label class="field">Links one per line, key=url<textarea id="peopleLinks" rows="4"></textarea></label>
    <label class="field">Flexible facts one per line, key=value<textarea id="peopleFacts" rows="4" placeholder="favorite=coffee&#10;met_at=Da Nang"></textarea></label>
    <label class="field">Notes<textarea id="peopleNotes" rows="4"></textarea></label>
    <div class="people-actions">
      <button id="peopleSaveButton" type="button">Save Local</button>
      <button id="peopleSaveSyncButton" type="button">Save + Sync Name</button>
      <button id="peopleSyncNameButton" type="button">Sync Name Only</button>
      <button id="peopleEnrollButton" type="button">Enroll Identity</button>
    </div>
  `;
  root.append(editor);
  editor.querySelector("#peopleEditorThumb").append(renderFaceThumb(person, "large"));
  setText(editor, "#peopleEditorTitle", person.display_name || "Unnamed face");
  if (conflict) {
    const banner = editor.querySelector("#peopleConflict");
    banner.className = "people-conflict";
    banner.textContent = `Name conflict: local "${conflict.local_name}" vs Immich "${conflict.immich_name}"`;
  }
  const draft = state.peopleEditorDirty ? state.peopleDraft : null;
  editor.querySelector("#peopleName").value = draft?.display_name ?? person.display_name ?? "";
  editor.querySelector("#peopleAliases").value = draft?.aliases ?? (person.aliases || []).join(", ");
  editor.querySelector("#peoplePhone").value = draft?.phone ?? person.phone ?? "";
  editor.querySelector("#peopleAddress").value = draft?.address ?? person.address ?? "";
  editor.querySelector("#peopleAge").value = draft?.age ?? person.age ?? "";
  editor.querySelector("#peopleWhereLives").value = draft?.where_lives ?? person.where_lives ?? "";
  editor.querySelector("#peopleRelationship").value = draft?.relationship ?? person.relationship ?? "";
  editor.querySelector("#peopleFirstMet").value = draft?.first_met ?? person.first_met ?? "";
  editor.querySelector("#peopleLinks").value = draft?.links ?? peopleLinksText(person.links || {});
  editor.querySelector("#peopleFacts").value = draft?.facts ?? peopleLinksText(person.facts || {});
  editor.querySelector("#peopleNotes").value = draft?.notes ?? person.notes ?? "";
  for (const input of editor.querySelectorAll("input, textarea")) {
    input.addEventListener("input", () => {
      state.peopleEditorDirty = true;
      capturePeopleDraft();
    });
  }
  editor.querySelector("#peopleSaveButton").addEventListener("click", () => saveSelectedPerson(false));
  editor.querySelector("#peopleSaveSyncButton").addEventListener("click", () => saveSelectedPerson(true));
  editor.querySelector("#peopleSyncNameButton").addEventListener("click", syncSelectedPersonName);
  editor.querySelector("#peopleEnrollButton").addEventListener("click", enrollSelectedPersonIdentity);
}


async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    state.peopleRegistry = (await api("/api/people/status")).people_registry;
    state.people = (await api("/api/people")).people;
    state.identity = (await api("/api/identity/status")).identity;
    state.identityContacts = (await api("/api/identity/contacts")).contacts;
    updatePageStatus();
    renderPeopleRegistry();
  } catch (error) {
    updatePageStatus(error);
    console.error(error);
  } finally {
    refreshInFlight = false;
  }
}

function selectPerson(personId) {
  state.selectedPersonId = personId;
  state.peopleEditorDirty = false;
  state.peopleDraft = null;
  renderPeopleRegistry();
}

async function syncPeopleRegistry() {
  try {
    const result = await api("/api/people/sync", {
      method: "POST",
      body: JSON.stringify({ push_names: false }),
    });
    state.peopleEditorDirty = false;
    state.peopleDraft = null;
    await refresh();
    alert(`Immich sync: ${result.sync.status} · remote ${result.sync.remote_count ?? 0}`);
  } catch (error) {
    alert(error.message);
  }
}

async function saveSelectedPerson(syncName) {
  if (!state.selectedPersonId) return;
  let payload;
  try {
    payload = peopleFormPayload(syncName);
  } catch (error) {
    alert(`Links are invalid: ${error.message}`);
    return;
  }
  try {
    await api(`/api/people/${encodeURIComponent(state.selectedPersonId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.peopleEditorDirty = false;
    state.peopleDraft = null;
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}

async function syncSelectedPersonName() {
  if (!state.selectedPersonId) return;
  try {
    await api(`/api/people/${encodeURIComponent(state.selectedPersonId)}/sync-name`, { method: "POST" });
    state.peopleEditorDirty = false;
    state.peopleDraft = null;
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}

async function enrollSelectedPersonIdentity() {
  if (!state.selectedPersonId) return;
  const person = state.people.find((item) => item.person_id === state.selectedPersonId);
  if (!person?.display_name && !document.querySelector("#peopleName")?.value.trim()) {
    alert("Add a name before enrolling identity.");
    return;
  }
  if (state.peopleEditorDirty) {
    await saveSelectedPerson(false);
  }
  try {
    const payload = {
      aliases: (document.querySelector("#peopleAliases")?.value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    };
    const result = await api(`/api/people/${encodeURIComponent(state.selectedPersonId)}/enroll-identity`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refresh();
    const enrollment = result.identity_enrollment || {};
    const sampleCount = enrollment.contact_sample_count || enrollment.sample_count_added_or_updated || 0;
    alert(`Identity enrolled: ${enrollment.display_name} (${sampleCount} samples)`);
  } catch (error) {
    alert(error.message);
  }
}


document.querySelector("#peoplePageRefreshButton")?.addEventListener("click", refresh);
document.querySelector("#peoplePageSyncButton")?.addEventListener("click", syncPeopleRegistry);

refresh().catch((error) => {
  updatePageStatus(error);
  console.error(error);
});

window.setInterval(() => {
  refresh().catch((error) => {
    updatePageStatus(error);
    console.error(error);
  });
}, 5000);
