"""VEKRA single-operator MVP. Python 3.12+, stdlib WSGI + SQLite."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server

ROOT = Path(__file__).parent
DB = os.environ.get('DATABASE_PATH', str(ROOT / 'data' / 'vektra.sqlite3'))
PUBLIC_URL = os.environ.get('PUBLIC_URL', 'http://localhost:8000').rstrip('/')
PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
STATUSES = ('new', 'contacted', 'meeting', 'won', 'lost')
PLANS = ('Не выбран', 'Starter', 'Professional', 'Enterprise')


def connect():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS leads (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL, company TEXT NOT NULL,
          contact TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '',
          plan TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
          notes TEXT NOT NULL DEFAULT '', draft TEXT NOT NULL DEFAULT '',
          consent_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
        ''')


class HTTPError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def clean(data, key, limit=200, required=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise HTTPError(400, 'Некорректное поле: ' + key)
    value = value.strip()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise HTTPError(400, 'Некорректная кодировка поля: ' + key)
    if required and not value:
        raise HTTPError(400, 'Заполните поле: ' + key)
    return value


def score(lead):
    points = 20
    reasons = []
    for field, weight, reason in [('company', 15, 'Указана компания'), ('website', 15, 'Указан сайт'),
                                  ('contact', 10, 'Указано контактное лицо')]:
        if lead[field]:
            points += weight
            reasons.append(reason)
    if lead['plan'] in ('Professional', 'Enterprise'):
        points += 20
        reasons.append('Интерес к расширенному тарифу')
    if lead['status'] == 'meeting':
        points += 20
        reasons.append('Назначена встреча')
    return {'points': points, 'grade': 'A' if points >= 70 else 'B' if points >= 45 else 'C',
            'reasons': reasons, 'method': 'Правила приоритизации, не вероятность сделки'}


def limited(bucket, maximum, seconds):
    now = int(time.time())
    with connect() as db:
        db.execute('DELETE FROM limits WHERE expires < ?', (now,))
        db.execute('INSERT INTO limits VALUES (?, 0, ?) ON CONFLICT DO NOTHING', (bucket, now + seconds))
        db.execute('UPDATE limits SET count=count+1 WHERE bucket=?', (bucket,))
        row = db.execute('SELECT count FROM limits WHERE bucket=?', (bucket,)).fetchone()
        if row['count'] > maximum:
            raise HTTPError(429, 'Слишком много попыток. Попробуйте позже.')


def authorized(env):
    cookie = SimpleCookie()
    try:
        cookie.load(env.get('HTTP_COOKIE', ''))
        token = cookie['vektra_session'].value
    except (KeyError, ValueError, CookieError):
        raise HTTPError(401, 'Войдите в кабинет')
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row = db.execute('SELECT expires FROM sessions WHERE token=?', (token_hash,)).fetchone()
    if not row or row['expires'] <= time.time():
        raise HTTPError(401, 'Сессия завершена. Войдите снова.')
    return token_hash


def body(env):
    if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
        raise HTTPError(415, 'Требуется application/json')
    # Explicit origin comparison protects mutations, including login CSRF.
    if env.get('HTTP_ORIGIN') != PUBLIC_URL:
        raise HTTPError(403, 'Недопустимый источник запроса')
    try:
        size = int(env.get('CONTENT_LENGTH') or 0)
        if not 0 < size <= 16384:
            raise ValueError()
        data = json.loads(env['wsgi.input'].read(size))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeDecodeError):
        raise HTTPError(400, 'Некорректный JSON или слишком большой запрос')


def cookie(value, age):
    secure = '; Secure' if PUBLIC_URL.startswith('https://') else ''
    return ('Set-Cookie', f'vektra_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{secure}')


def route(env):
    method, path = env['REQUEST_METHOD'], env['PATH_INFO']
    if method == 'GET' and path in ('/', '/admin', '/admin/', '/app.js', '/admin.js', '/service.css', '/theme.css'):
        name = {'/': 'index.html', '/admin': 'admin.html', '/admin/': 'admin.html'}.get(path, path[1:])
        mime = 'text/html' if name.endswith('.html') else 'text/javascript' if name.endswith('.js') else 'text/css'
        return 200, (ROOT / name).read_bytes(), [('Content-Type', mime + '; charset=utf-8')]
    if method == 'GET' and path == '/health':
        with connect() as db:
            db.execute('SELECT 1').fetchone()
        return 200, {'ok': True}, []
    data = body(env) if method in ('POST', 'PATCH', 'DELETE') else {}
    ip = env.get('REMOTE_ADDR', 'unknown')  # Never trust user-supplied X-Forwarded-For.
    if method == 'POST' and path == '/api/login':
        limited('login:' + ip, 10, 900)
        candidate = clean(data, 'password', 256, True)
        if not PASSWORD or not hmac.compare_digest(candidate.encode(), PASSWORD.encode()):
            raise HTTPError(401, 'Неверный пароль')
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (now,))
            db.execute('INSERT INTO sessions VALUES (?, ?)', (hashlib.sha256(token.encode()).hexdigest(), now + 28800))
        return 200, {'ok': True}, [cookie(token, 28800)]
    if method == 'POST' and path == '/api/requests':
        limited('intake:' + ip, 20, 3600)
        if data.get('consent') is not True:
            raise HTTPError(400, 'Нужно согласие на обработку заявки')
        email = clean(data, 'email', 254, True)
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise HTTPError(400, 'Проверьте email')
        company = clean(data, 'company', 200, True)
        website = clean(data, 'website', 500)
        try:
            valid_site = not website or (urlsplit(website).scheme in ('http', 'https') and bool(urlsplit(website).netloc))
        except ValueError:
            valid_site = False
        if not valid_site:
            raise HTTPError(400, 'Сайт должен начинаться с https:// или http://')
        plan = clean(data, 'plan') or 'Не выбран'
        if plan not in PLANS:
            raise HTTPError(400, 'Неизвестный тариф')
        contact = clean(data, 'contact')
        now = int(time.time())
        with connect() as db:
            cur = db.execute('INSERT INTO leads (email,company,contact,website,plan,consent_at,created_at) VALUES (?,?,?,?,?,?,?)',
                             (email, company, contact, website, plan, now, now))
            lead_id = cur.lastrowid
        return 201, {'id': lead_id, 'message': 'Заявка сохранена. Номер: ' + str(lead_id)}, []
    if path.startswith('/api/'):
        token = authorized(env)
        if method == 'GET' and path == '/api/leads':
            with connect() as db:
                rows = [dict(row) for row in db.execute('SELECT * FROM leads ORDER BY created_at DESC,id DESC LIMIT 1000')]
            for row in rows:
                row['score'] = score(row)
            return 200, {'leads': rows}, []
        if method == 'POST' and path == '/api/logout':
            with connect() as db:
                db.execute('DELETE FROM sessions WHERE token=?', (token,))
            return 200, {'ok': True}, [cookie('', 0)]
        match = re.fullmatch(r'/api/leads/(\d+)(/draft)?', path)
        if match:
            lead_id, draft_action = int(match[1]), match[2]
            with connect() as db:
                row = db.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
                if not row:
                    raise HTTPError(404, 'Лид не найден')
                if method == 'DELETE' and not draft_action:
                    db.execute('DELETE FROM leads WHERE id=?', (lead_id,))
                    return 200, {'ok': True}, []
                if method == 'PATCH' and not draft_action:
                    status = clean(data, 'status', required=True)
                    if status not in STATUSES:
                        raise HTTPError(400, 'Неизвестный статус')
                    notes = clean(data, 'notes', 4000)
                    draft = clean(data, 'draft', 6000)
                    db.execute('UPDATE leads SET status=?,notes=?,draft=? WHERE id=?', (status, notes, draft, lead_id))
                    return 200, {'ok': True}, []
                if method == 'POST' and draft_action:
                    name = row['contact'] or 'коллеги'
                    draft = (f'{name}, добрый день!\n\nСпасибо за интерес к ВЕКРА. Вы оставили заявку от компании '
                             f'«{row["company"]}»' + (f' по тарифу {row["plan"]}' if row['plan'] != 'Не выбран' else '') +
                             '. Как сейчас ваша команда расставляет приоритеты среди входящих заявок?\n\n'
                             'Предлагаю обсудить ваш процесс продаж и подобрать следующий шаг. Когда вам удобно?')
                    db.execute('UPDATE leads SET draft=? WHERE id=?', (draft, lead_id))
                    return 200, {'draft': draft, 'method': 'Персонализированный шаблон; проверьте перед отправкой'}, []
    raise HTTPError(404, 'Страница не найдена')


def app(env, start_response):
    try:
        status, payload, headers = route(env)
    except HTTPError as error:
        status, payload, headers = error.status, {'error': error.message}, []
    except Exception:
        import traceback
        traceback.print_exc()
        status, payload, headers = 500, {'error': 'Сервер временно недоступен. Попробуйте позже.'}, []
    if not isinstance(payload, bytes):
        payload = json.dumps(payload, ensure_ascii=False).encode()
        headers.append(('Content-Type', 'application/json; charset=utf-8'))
    headers += [('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
                ('Referrer-Policy', 'same-origin'),
                ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")]
    reason = {200:'OK',201:'Created',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',415:'Unsupported Media Type',429:'Too Many Requests',500:'Internal Server Error'}[status]
    start_response(f'{status} {reason}', headers)
    return [payload]


def validate_config():
    if len(PASSWORD) < 16:
        raise RuntimeError('Задайте ADMIN_PASSWORD длиной минимум 16 символов')
    parsed = urlsplit(PUBLIC_URL)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path:
        raise RuntimeError('PUBLIC_URL должен быть полным origin, например https://vektra.example')


if __name__ == '__main__':
    validate_config()
    init_db()
    with make_server('0.0.0.0', int(os.environ.get('PORT', '8000')), app) as httpd:
        print('ВЕКРА: ' + PUBLIC_URL, flush=True)
        httpd.serve_forever()
