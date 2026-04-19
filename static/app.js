const appForm = document.getElementById('appForm');
const appsList = document.getElementById('appsList');
const statusEl = document.getElementById('status');
const refreshBtn = document.getElementById('refreshBtn');
const checkUpdatesBtn = document.getElementById('checkUpdatesBtn');
const refreshLogsBtn = document.getElementById('refreshLogsBtn');
const logPane = document.getElementById('logPane');

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className = isError ? 'error' : '';
}

function cardTemplate(app) {
  const updateFlag = app.update_available
    ? `<p class="update-flag">Update available (${app.pending_commits ?? 0} commit(s))</p>`
    : '';

  return `
    <article class="card">
      <h3>${app.application_name}</h3>
      <p>Port: ${app.application_port}</p>
      <p>Path: /${app.web_path}</p>
      <p>PID: ${app.pid ?? 'n/a'}</p>
      <p>Folder: ${app.application_folder ?? 'n/a'}</p>
      ${updateFlag}
      <button class="delete" data-id="${app.id}">Delete</button>
    </article>
  `;
}

async function fetchApps() {
  const response = await fetch('/api/apps');
  if (!response.ok) {
    throw new Error('Failed to fetch applications');
  }
  return response.json();
}

async function renderApps() {
  try {
    const apps = await fetchApps();
    appsList.innerHTML = apps.length ? apps.map(cardTemplate).join('') : '<p>No applications configured.</p>';
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function fetchLogs() {
  const response = await fetch('/api/logs');
  if (!response.ok) {
    throw new Error('Failed to fetch logs');
  }
  return response.json();
}

function renderLogEntry(log) {
  const level = (log.level || 'info').toLowerCase();
  const date = log.timestamp ? new Date(log.timestamp).toLocaleString() : 'unknown-time';
  const appName = log.app_name ? ` [${log.app_name}]` : '';
  return `
    <article class="log-entry ${level}">
      <p class="log-meta">${date} | ${level.toUpperCase()}${appName}</p>
      <p>${log.message || ''}</p>
    </article>
  `;
}

async function renderLogs() {
  try {
    const logs = await fetchLogs();
    const ordered = [...logs].reverse();
    logPane.innerHTML = ordered.length ? ordered.map(renderLogEntry).join('') : '<p>No log entries yet.</p>';
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function checkUpdates() {
  setStatus('Checking GitHub updates...');
  try {
    const response = await fetch('/api/apps/check-updates', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || 'Update check failed');
    }

    const updatedCount = (result.results || []).filter((item) => item.status === 'updated').length;
    setStatus(`Update check complete. Updated ${updatedCount} app(s).`);
    await renderApps();
    await renderLogs();
  } catch (error) {
    setStatus(error.message, true);
  }
}

appForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setStatus('Adding application...');

  const formData = new FormData(appForm);
  const payload = Object.fromEntries(formData.entries());

  for (const key of Object.keys(payload)) {
    if (payload[key] === '') {
      delete payload[key];
    }
  }

  try {
    const response = await fetch('/api/apps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || 'Failed to add application');
    }

    appForm.reset();
    setStatus(`Added ${result.application_name}.`);
    await renderApps();
    await renderLogs();
  } catch (error) {
    setStatus(error.message, true);
  }
});

appsList.addEventListener('click', async (event) => {
  const button = event.target.closest('button.delete');
  if (!button) return;

  const appId = button.dataset.id;
  if (!appId) return;

  setStatus('Deleting application...');

  try {
    const response = await fetch(`/api/apps/${appId}`, { method: 'DELETE' });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || 'Failed to delete application');
    }

    setStatus('Application deleted.');
    await renderApps();
    await renderLogs();
  } catch (error) {
    setStatus(error.message, true);
  }
});

refreshBtn.addEventListener('click', () => {
  renderApps();
});

checkUpdatesBtn.addEventListener('click', () => {
  checkUpdates();
});

refreshLogsBtn.addEventListener('click', () => {
  renderLogs();
});

renderApps();
renderLogs();
