"""Sync Test photos and publish only camera assets to the website repository."""
import fcntl
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / '.server/giles-camera'
REPO = ROOT / 'website'

def git(*args):
    return subprocess.run(['/usr/bin/git', '-C', str(REPO), *args],
                          check=True, capture_output=True, text=True).stdout.strip()

def main():
    os.umask(0o077)
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    os.environ['TMPDIR'] = str(ROOT / 'tmp')
    lock = (ROOT / 'publish.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if git('status', '--porcelain'):
            raise RuntimeError('Website checkout has local changes; stopping to preserve them')
        if git('branch', '--show-current') != 'main':
            raise RuntimeError('Website checkout is not on main')
        git('pull', '--ff-only', 'origin', 'main')
        subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'download.py'), '--days', '30'], check=True)
        source = ROOT / 'site-files'
        metadata = json.loads((source / '_data/camera.json').read_text())
        if not metadata:
            raise RuntimeError('No verified camera photos to publish')
        for photo in metadata:
            for field in ['image', 'thumbnail']:
                relative = Path(photo[field].lstrip('/'))
                if relative.parts[:2] != ('assets', 'camera') or '..' in relative.parts:
                    raise RuntimeError('Unexpected camera image path')
                destination = REPO / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, destination)
        (REPO / '_data').mkdir(exist_ok=True)
        shutil.copyfile(source / '_data/camera.json', REPO / '_data/camera.json')
        git('add', '--', '_data/camera.json', 'assets/camera')
        if git('diff', '--cached', '--name-only'):
            git('commit', '-m', 'Update daily river crossing camera photos')
        # Retry a previous unpushed commit even when this run found no new photo.
        git('push', 'origin', 'HEAD:main')
        status = {'last_success': datetime.now().astimezone().isoformat(),
                  'photos': len(metadata), 'latest_capture': metadata[-1]['captured_at']}
        (ROOT / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
        print('Camera sync complete:', status, flush=True)
    except Exception as error:
        (ROOT / 'last-error.txt').write_text(datetime.now().astimezone().isoformat() + '\n' + str(error) + '\n')
        raise

if __name__ == '__main__':
    main()
