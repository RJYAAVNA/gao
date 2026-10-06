// Identity boundaries: never let an old page submit under a different user's cookie.
(() => {
  const context = document.querySelector('meta[name="auth-context"]')?.content || '';
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('ledger-identity') : null;
  const controllers = new Set();
  let invalid = false;
  let ready = false;
  let verification = null;
  function hide() {
    ready = false;
    document.documentElement.style.visibility = 'hidden';
    controllers.forEach(c => c.abort());
  }
  function changed(next) {
    if (next === context) return;
    invalid = true;
    hide();
    location.replace('/login');
  }
  channel?.addEventListener('message', e => changed(e.data.context));
  window.addEventListener('storage', e => {
    if (e.key === 'ledger-auth-context') changed(e.newValue || '');
  });
  function publish(next) {
    channel?.postMessage({context: next});
    try { localStorage.setItem('ledger-auth-context', next); } catch (_) { /* optional */ }
  }
  function verify() {
    if (!verification) verification = checkIdentity().finally(() => { verification = null; });
    return verification;
  }
  async function checkIdentity() {
    if (context) hide();
    try {
      const response = await fetch('/api/auth/me', {cache: 'no-store'});
      const body = await response.json();
      if (!context && !response.ok) { publish(''); return; }
      if (!context && response.ok) { location.replace('/'); return; }
      if (!response.ok || body.auth_context !== context) { changed(body.auth_context || ''); return; }
      if (!invalid) {
        ready = true;
        document.documentElement.style.visibility = '';
        publish(context);
      }
    } catch (_) {
      location.replace('/offline');
    }
  }
  window.addEventListener('pageshow', event => { if (event.persisted || !ready) verify(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') verify();
    else if (context) hide();
  });
  document.addEventListener('submit', e => {
    if (invalid) { e.preventDefault(); return; }
    const form = e.target;
    if ((form.method || '').toLowerCase() !== 'post') return;
    for (const [name, value] of [['csrf_token', csrf], ['auth_context', context]]) {
      if (!form.querySelector(`[name="${name}"]`)) {
        const input = document.createElement('input');
        input.type = 'hidden'; input.name = name; input.value = value;
        form.appendChild(input);
      }
    }
  });
  async function api(url, options = {}) {
    if (!ready) await verify();
    if (invalid || !ready) throw new Error('identity_changed');
    const controller = new AbortController();
    controllers.add(controller);
    try {
      const response = await fetch(url, {...options, cache: 'no-store', signal: controller.signal,
        headers: {...options.headers, 'X-CSRFToken': csrf, 'X-Auth-Context': context}});
      if (response.status === 401 ||
          (response.headers.get('X-Auth-Context') || '') !== context) {
        changed(response.headers.get('X-Auth-Context') || '');
        throw new Error('identity_changed');
      }
      if (invalid) throw new Error('identity_changed');
      return response;
    } finally { controllers.delete(controller); }
  }
  window.ledgerIdentity = {api, async logout() {
    const response = await fetch('/api/auth/logout', {method: 'POST',
      headers: {'X-CSRFToken': csrf, 'X-Auth-Context': context}});
    if (response.ok || response.status === 401) { publish(''); location.replace('/login'); }
    else { await verify(); }
  }};
})();
