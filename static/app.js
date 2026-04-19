const appForm = document.getElementById('appForm');
const appsList = document.getElementById('appsList');
const statusEl = document.getElementById('status');
const refreshBtn = document.getElementById('refreshBtn');

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className = isError ? 'error' : '';
}

function cardTemplate(app) {
  return `
    <article class="card">
      <h3>${app.application_name}</h3>
      <p>Port: ${app.application_port}</p>
      <p>Path: /${app.web_path}</p>
      <p>PID: ${app.pid ?? 'n/a'}</p>
      <p>Folder: ${app.application_folder ?? 'n/a'}</p>
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
  } catch (error) {
    setStatus(error.message, true);
  }
});

refreshBtn.addEventListener('click', () => {
  renderApps();
});

renderApps();
