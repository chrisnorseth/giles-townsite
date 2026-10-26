"""Download a date-filtered shared gallery's Test photos, or run a daily sync.

Runtime files belong in ~/.server/giles-camera; credentials never enter Git.
"""
import argparse
import fcntl
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout
import auth

ROOT = Path.home() / '.server/giles-camera'
ZONE = ZoneInfo('America/Denver')
CAMERA = '869736072671174'
SCROLL = '#shared-galleries-collection-details-infinite-scroll-container'

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)

def capture_date(src):
    match = re.search(r'-(\d{14})-', src)
    if not match:
        return None
    return datetime.strptime(match[1], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).astimezone(ZONE)

def distance_from_test_time(captured):
    return abs((captured.hour * 3600 + captured.minute * 60 + captured.second) - (12 * 3600 + 49 * 60))

def daily_candidates(rows):
    selected = {}
    for row in rows:
        captured = capture_date(row['src'])
        if captured is None:
            continue
        day = captured.date()
        rank = (distance_from_test_time(captured), captured.isoformat())
        if day not in selected or rank < selected[day][0]:
            selected[day] = (rank, row)
    return [value[1] for _, value in sorted(selected.items(), reverse=True)]

def open_gallery(page, start, end):
    page.goto('https://app.moultriemobile.com/gallery', wait_until='domcontentloaded')
    try:
        page.get_by_test_id('chip-tab-label-SharedGalleries-ChipNavigation').wait_for(timeout=60000)
    except PlaywrightTimeout as error:
        if 'login.moultriemobile.com' in page.url or '/authentication/' in page.url:
            raise RuntimeError('Moultrie login needs renewal; previous website photos are unchanged') from error
        raise
    auth.save(page.context, page)
    page.get_by_test_id('chip-tab-label-SharedGalleries-ChipNavigation').click()
    page.get_by_test_id('collection-item-SharedByTimP.-CollectionItemComponent').click()
    page.locator(SCROLL).wait_for()
    page.get_by_test_id('filter-button-GalleryToolbar').click()
    clear = page.get_by_test_id('clear-all-button-FilterPanelComponent')
    if clear.is_enabled():
        clear.click()
    page.get_by_test_id('filter-button-GalleryToolbar').click()
    page.get_by_test_id('sort-button-DropdownMenu').click()
    page.get_by_test_id('dropdown-item-TimeTaken(NewestFirst)-button-DropdownMenu').click()
    page.wait_for_timeout(2000)

def collect(page, start):
    found = {}
    previous = None
    stable = 0
    for step in range(100):
        rows = page.locator('.image-item').evaluate_all('''nodes => nodes.filter(n => [...n.querySelectorAll('.rounded-container-text')].some(t => t.textContent.trim() === 'Test')).map(n => ({src:n.querySelector('img.main-image').src}))''')
        for row in rows:
            if capture_date(row['src']):
                found[row['src']] = row
        state = page.locator(SCROLL).evaluate('(n)=>({height:n.scrollHeight,top:n.scrollTop,count:n.querySelectorAll(".image-item").length})')
        stable = stable + 1 if previous == state else 0
        print('Scan', step, 'gallery items', state['count'], 'Test photos', len(found), flush=True)
        sources = page.locator('.image-item img.main-image').evaluate_all('(ns)=>ns.map(n=>n.src)')
        dates = [capture_date(src) for src in sources]
        dates = [date for date in dates if date is not None]
        if dates and min(dates).date() < start:
            return list(found.values())
        if stable >= 6:
            return list(found.values())
        previous = state
        page.locator(SCROLL).evaluate('(n)=>{n.scrollTop=n.scrollHeight}')
        page.wait_for_timeout(1800)
    raise RuntimeError('Archive scan did not reach its end')

def download(page, rows, start, end):
    manifest_path = ROOT / 'archive.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    known = {row['id'] for row in manifest}
    originals = ROOT / 'originals'
    originals.mkdir(exist_ok=True)
    failures = []
    for row in rows:
        captured = capture_date(row['src'])
        if not captured or not start <= captured.date() <= end:
            continue
        key = captured.strftime('%Y%m%dT%H%M%S')
        if key in known:
            continue
        try:
            card = page.locator('.image-item').filter(has=page.locator('img.main-image[src=' + json.dumps(row['src']) + ']'))
            if card.get_by_text('Test', exact=True).count() != 1:
                raise RuntimeError('Test label could not be verified')
            card.locator('.image-overlay').click(timeout=15000)
            camera = page.get_by_test_id('carousel-media-details-camera-id-CarouselMediaDetails')
            camera.wait_for()
            if camera.inner_text().strip() != 'ID: ' + CAMERA:
                raise RuntimeError('Different camera; skipped')
            display_time = page.get_by_test_id('carousel-media-details-time-CarouselMediaDetails').inner_text().strip()
            display_date = page.get_by_test_id('carousel-media-details-date-CarouselMediaDetails').inner_text().strip()
            actual = datetime.strptime(display_date + ' ' + str(captured.year) + ' ' + display_time,
                                       '%a, %b %d %Y %I:%M %p').replace(tzinfo=ZONE)
            if not start <= actual.date() <= end:
                continue
            captured = actual
            with page.expect_download(timeout=30000) as event:
                page.get_by_test_id('download-button-CarouselMediaToolbar').click()
            target = originals / (key + '.jpg')
            event.value.save_as(str(target))
            with Image.open(target) as image:
                image.verify()
            manifest.append({'id': key, 'captured_at': captured.isoformat(), 'original': target.name})
            known.add(key)
            write_json(manifest_path, manifest)
            print('Downloaded Test', captured.isoformat(), flush=True)
        except Exception as error:
            failures.append(key)
            print('Skipped', key, type(error).__name__, str(error).splitlines()[0][:150], flush=True)
        finally:
            back = page.get_by_test_id('carousel-back-button-CarouselTopBar')
            if back.is_visible():
                back.click()
    if failures:
        raise RuntimeError('Some photos could not be downloaded: ' + ', '.join(failures))
    return manifest

def render(manifest):
    output = ROOT / 'site-files'
    photos = output / 'assets/camera'
    photos.mkdir(parents=True, exist_ok=True)
    records = []
    selected = {}
    for row in manifest:
        captured = datetime.fromisoformat(row['captured_at']).astimezone(ZONE)
        day = captured.date()
        rank = (distance_from_test_time(captured), row['captured_at'])
        if day not in selected or rank < selected[day][0]:
            selected[day] = (rank, row)
    for _, row in sorted(selected.values(), key=lambda value: value[1]['captured_at']):
        captured = datetime.fromisoformat(row['captured_at'])
        name = row['id'] + '.jpg'
        thumb = row['id'] + '-thumb.jpg'
        if not (photos / name).exists() or not (photos / thumb).exists():
            with Image.open(ROOT / 'originals' / row['original']) as source:
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1600, 1200))
                image.save(photos / name, 'JPEG', quality=83, optimize=True)
                image.thumbnail((480, 360))
                image.save(photos / thumb, 'JPEG', quality=78, optimize=True)
        records.append({'captured_at': row['captured_at'],
                        'label': captured.strftime('%B %-d, %Y at %-I:%M %p') + ' Mountain Time',
                        'month_label': captured.strftime('%B %Y'),
                        'image': '/assets/camera/' + name,
                        'thumbnail': '/assets/camera/' + thumb})
    write_json(output / '_data/camera.json', records)
    print('Prepared', len(records), 'website photos', flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cdp', action='store_true')
    parser.add_argument('--current-gallery', action='store_true')
    parser.add_argument('--days', type=int, default=3)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'browsers')
    os.environ['TMPDIR'] = str(ROOT / 'tmp')
    lock = (ROOT / 'sync.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    end = datetime.now(ZONE).date()
    start = end - timedelta(days=args.days - 1)
    with sync_playwright() as p:
        if args.cdp:
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
            context = browser.contexts[0]
            page = context.pages[0]
        else:
            context = p.chromium.launch_persistent_context(str(ROOT / 'browser-profile'), headless=True)
            auth.restore(context)
            page = context.pages[0] if context.pages else context.new_page()
        try:
            if not args.current_gallery:
                open_gallery(page, start, end)
            rows = collect(page, start)
            manifest = download(page, rows, start, end)
            render(manifest)
            auth.save(context, page)
        finally:
            if not args.cdp:
                context.close()

if __name__ == '__main__':
    main()
