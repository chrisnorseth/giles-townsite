"""Verify the published camera photo and send deduplicated ntfy alerts."""
import json
import os
import time
from datetime import datetime, time as clock_time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path.home() / '.server/giles-camera'
SITE = 'https://christiannorseth.com/giles-townsite/'
ZONE = ZoneInfo('America/Denver')
DEADLINE = clock_time(14, 15)

class LatestPhoto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.capture = None
        self.image = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif 'camera-latest' in attrs.get('class', '').split():
                self.depth = 1
        if self.depth and tag == 'time':
            self.capture = attrs.get('datetime')
        if self.depth and tag == 'img':
            self.image = attrs.get('src')

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1

def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}

def save_state(value):
    path = ROOT / 'notification-state.json'
    temp = path.with_suffix('.tmp')
    with os.fdopen(os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
        json.dump(value, output, indent=2)
    temp.replace(path)

def published_photo():
    request = Request(SITE, headers={'Cache-Control': 'no-cache', 'User-Agent': 'GilesCameraMonitor/1.0'})
    with urlopen(request, timeout=20) as response:
        page_url = response.geturl()
        parser = LatestPhoto()
        parser.feed(response.read(2_000_000).decode('utf-8'))
    if not parser.capture or not parser.image:
        raise ValueError('Homepage has no dated camera photo')
    captured = datetime.fromisoformat(parser.capture)
    if captured.tzinfo is None:
        raise ValueError('Camera timestamp has no timezone')
    image_url = urljoin(page_url, parser.image)
    if urlsplit(image_url).netloc != urlsplit(page_url).netloc:
        raise ValueError('Unexpected camera image host')
    with urlopen(image_url, timeout=20) as response:
        if not response.headers.get_content_type().startswith('image/') or not response.read(1):
            raise ValueError('Published camera image is unavailable')
    return captured.astimezone(ZONE)

def send(title, message, recovery=False):
    config = read_json(ROOT / 'ntfy.json')
    if config.get('server') != 'https://ntfy.sh':
        raise ValueError('Expected ntfy.sh configuration')
    request = Request(config['server'] + '/' + config['topic'], data=message.encode('utf-8'),
                      headers={'Title': title, 'Tags': 'white_check_mark' if recovery else 'warning',
                               'Click': SITE, 'Content-Type': 'text/plain; charset=utf-8'}, method='POST')
    with urlopen(request, timeout=20) as response:
        response.read()

def problem(stage, captured, expected, status):
    if stage:
        descriptions = {'repository': 'preparing the website repository',
                        'download': 'retrieving photos (the Moultrie login may need renewal)',
                        'publish': 'pushing the website update'}
        return 'The camera update failed while ' + descriptions.get(stage, 'running') + '.'
    latest = status.get('latest_capture')
    if latest and datetime.fromisoformat(latest).astimezone(ZONE).date() >= expected:
        return 'A recent photo was processed, but the homepage or its image could not be verified.'
    if captured:
        return "Today's Test photo is missing. The website still shows " + captured.strftime('%B %-d') + '.'
    return 'The published camera photo could not be verified. Check the website and camera routine.'

def check(stage=None, attempts=1, now=None):
    if not (ROOT / 'ntfy.json').exists():
        return
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    after_deadline = now.time() >= DEADLINE
    state = read_json(ROOT / 'notification-state.json')
    # Before the retry, only check for recovery from an existing incident.
    if not after_deadline and not state.get('active'):
        return
    expected = now.date() if after_deadline else now.date() - timedelta(days=1)
    captured = None
    healthy = False
    for attempt in range(attempts):
        try:
            captured = published_photo()
            healthy = expected <= captured.date() <= now.date() and captured <= now + timedelta(minutes=5)
        except Exception as error:
            print('Camera website verification:', type(error).__name__, flush=True)
        if healthy:
            break
        if attempt + 1 < attempts:
            time.sleep(30)
    state['last_check'] = now.isoformat()
    state['latest_published_capture'] = captured.isoformat() if captured else None
    state['healthy'] = healthy
    if healthy:
        today = now.date().isoformat()
        todays_photo = captured.date() == now.date()
        if state.get('active'):
            send('Giles camera recovered', 'Camera updates are working again. The latest photo is live.', recovery=True)
            state['last_notification'] = now.isoformat()
            if todays_photo:
                state['last_success_notification_date'] = today
        elif todays_photo and state.get('last_success_notification_date') != today:
            send('Giles camera updated', "Today's camera photo is live (" + captured.strftime('%B %-d at %-I:%M %p') + ' Mountain Time).', recovery=True)
            state['last_notification'] = now.isoformat()
            state['last_success_notification_date'] = today
        state['active'] = False
    elif after_deadline:
        state['problem'] = problem(stage, captured, expected, read_json(ROOT / 'status.json'))
        if not state.get('active'):
            send('Giles camera needs attention', state['problem'])
            state['last_notification'] = now.isoformat()
        state['active'] = True
    save_state(state)
    print('Published camera photo check:', 'healthy' if healthy else 'needs attention', flush=True)

def safe_check(stage=None, attempts=1):
    try:
        check(stage=stage, attempts=attempts)
    except Exception as error:
        # A notification-service outage must not break photo publishing or expose topic URLs.
        print('Camera notification check failed:', type(error).__name__, flush=True)

if __name__ == '__main__':
    os.umask(0o077)
    safe_check()
