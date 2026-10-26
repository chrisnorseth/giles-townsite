"""Keep Moultrie authentication private and reusable across browser restarts."""
import json
import os
from pathlib import Path

ROOT = Path.home() / '.server/giles-camera'
ORIGIN = 'https://app.moultriemobile.com'
STATE = ROOT / 'auth-state.json'

def restore(context):
    if not STATE.exists():
        return
    saved = json.loads(STATE.read_text())
    context.add_cookies(saved['storage'].get('cookies', []))
    app_storage = next((item.get('localStorage', []) for item in saved['storage'].get('origins', [])
                        if item['origin'] == ORIGIN), [])
    data = {'origin': ORIGIN, 'local': app_storage, 'session': saved.get('session', {})}
    context.add_init_script('''(() => {
      const data = %s;
      if (location.origin !== data.origin || sessionStorage.getItem('__giles_auth_restored')) return;
      for (const item of data.local) localStorage.setItem(item.name, item.value);
      for (const [name, value] of Object.entries(data.session)) sessionStorage.setItem(name, value);
      sessionStorage.setItem('__giles_auth_restored', '1');
    })();''' % json.dumps(data))

def save(context, page):
    if not page.url.startswith(ORIGIN + '/'):
        return False
    authenticated = page.get_by_test_id('chip-tab-label-SharedGalleries-ChipNavigation').is_visible()
    authenticated = authenticated or page.get_by_test_id('shared-galleries-details-container-SharedGalleriesCollection').is_visible()
    if not authenticated:
        return False
    session = page.evaluate('''() => Object.fromEntries(Object.entries(sessionStorage).filter(([key]) => key !== '__giles_auth_restored'))''')
    saved = {'storage': context.storage_state(indexed_db=True), 'session': session}
    temp = STATE.with_suffix('.tmp')
    with os.fdopen(os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
        json.dump(saved, output)
    temp.replace(STATE)
    STATE.chmod(0o600)
    return True
