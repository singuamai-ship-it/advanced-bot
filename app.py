import os
import hmac
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session,
    flash, render_template_string, abort
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '')

if len(app.config['SECRET_KEY']) < 24:
    raise RuntimeError('Railway SECRET_KEY minimum 24 characters set karo.')

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

if len(ADMIN_PASSWORD) < 12:
    raise RuntimeError('Railway ADMIN_PASSWORD minimum 12 characters set karo.')

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if not DATABASE_URL:
    raise RuntimeError(
        'Railway mein PostgreSQL service se DATABASE_URL reference variable add karo.'
    )

CSRFProtect(app)
Limiter(
    get_remote_address,
    app=app,
    default_limits=['200 per day', '60 per hour']
)

BASE = '''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Course Bot Admin</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b1020;color:#edf2ff;font:15px/1.5 system-ui}
main{max-width:1100px;margin:auto;padding:16px}
a{color:#91baff;text-decoration:none}
header,.row,nav{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
nav{justify-content:flex-start;margin:14px 0}
nav a,button,.btn{padding:9px 12px;border:1px solid #35496e;border-radius:8px;background:#1b2a48;color:#fff;font:inherit;cursor:pointer}
.card{background:#141d31;border:1px solid #2c3b5a;border-radius:13px;padding:15px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.big{font-size:27px;font-weight:800}
.muted{color:#a8b4ce}
label{display:block;margin:12px 0 4px}
input,textarea,select{width:100%;padding:10px;background:#0b1427;color:#fff;border:1px solid #334260;border-radius:8px;font:inherit}
textarea{min-height:80px}
.primary{background:#315caa}
.danger{background:#542b39}
.flash{padding:10px;border-radius:8px;background:#1b2a48;margin:8px 0}
.table{overflow-x:auto}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:8px;border-bottom:1px solid #2c3b5a;vertical-align:top}
small{overflow-wrap:anywhere}
.check{width:auto}
@media(max-width:600px){main{padding:10px}td,th{font-size:13px}}
</style>
</head>
<body>
<main>
{% if session.get('ok') %}
<header>
<b>📚 Course Bot Admin</b>
<form method="post" action="{{url_for('logout')}}">
<input type="hidden" name="csrf_token" value="{{csrf_token()}}">
<button>Logout</button>
</form>
</header>
<nav>
<a href="{{url_for('home')}}">Dashboard</a>
<a href="{{url_for('plans')}}">Plans</a>
<a href="{{url_for('orders')}}">Payments</a>
<a href="{{url_for('users')}}">Users</a>
<a href="{{url_for('settings')}}">Settings</a>
</nav>
{% endif %}
{% for cat,msg in get_flashed_messages(with_categories=true) %}
<div class="flash">{{msg}}</div>
{% endfor %}
{{body|safe}}
</main>
</body>
</html>'''


def page(body, **ctx):
    return render_template_string(
        BASE,
        body=render_template_string(body, **ctx)
    )


def connect():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=10
    )


def init_db():
    with connect() as c:
        with c.cursor() as q:
            q.execute("""
                CREATE TABLE IF NOT EXISTS settings(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
            """)
            q.execute("""
                CREATE TABLE IF NOT EXISTS plans(
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    price TEXT NOT NULL DEFAULT '0',
                    validity TEXT DEFAULT '',
                    videos TEXT DEFAULT '',
                    image TEXT DEFAULT '',
                    qr TEXT DEFAULT '',
                    caption TEXT DEFAULT '',
                    active BOOLEAN DEFAULT TRUE,
                    sort_order INTEGER DEFAULT 0
                )
            """)
            q.execute("""
                CREATE TABLE IF NOT EXISTS demos(
                    id BIGSERIAL PRIMARY KEY,
                    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                    media_type TEXT DEFAULT 'video',
                    media_id TEXT DEFAULT '',
                    media_url TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0
                )
            """)
            q.execute("""
                CREATE TABLE IF NOT EXISTS users(
                    telegram_user_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    last_seen TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            q.execute("""
                CREATE TABLE IF NOT EXISTS orders(
                    id BIGSERIAL PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL,
                    plan_id INTEGER,
                    plan_name TEXT DEFAULT '',
                    amount TEXT DEFAULT '',
                    screenshot_file_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ,
                    admin_note TEXT DEFAULT ''
                )
            """)
            q.execute("""
                INSERT INTO settings(key,value)
                VALUES('support_link','https://t.me/xylerigcc')
                ON CONFLICT(key) DO NOTHING
            """)


init_db()


def login_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not session.get('ok'):
            return redirect(url_for('login', next=request.path))
        return fn(*a, **kw)
    return w


def setting(key, default=''):
    with connect() as c:
        with c.cursor() as q:
            q.execute('SELECT value FROM settings WHERE key=%s', (key,))
            r = q.fetchone()
            return r['value'] if r else default


def set_setting(key, value):
    with connect() as c:
        with c.cursor() as q:
            q.execute(
                '''INSERT INTO settings(key,value) VALUES(%s,%s)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value''',
                (key, value)
            )


def token():
    return setting('bot_token') or os.getenv('BOT_TOKEN', '').strip()


def notify(uid, text):
    t = token()
    if not t:
        return False, 'Bot token not configured'
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{t}/sendMessage',
            json={'chat_id': int(uid), 'text': text},
            timeout=10
        ).json()
        return bool(r.get('ok')), r.get('description', 'Telegram API error')
    except Exception as e:
        app.logger.exception('Telegram notify failed')
        return False, str(e)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if (
            hmac.compare_digest(request.form.get('username', ''), ADMIN_USERNAME)
            and hmac.compare_digest(request.form.get('password', ''), ADMIN_PASSWORD)
        ):
            session.clear()
            session['ok'] = True
            return redirect(url_for('home'))

        flash('Username/password galat hai.')

    return page('''
        <div class="card" style="max-width:430px;margin:8vh auto">
        <h1>Admin Login</h1>
        <form method="post">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <label>Username</label>
        <input name="username" required>
        <label>Password</label>
        <input name="password" type="password" required>
        <p><button class="primary">Login</button></p>
        </form></div>
    ''')


@app.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    with connect() as c:
        with c.cursor() as q:
            q.execute("""
                SELECT
                (SELECT COUNT(*) FROM plans) plans,
                (SELECT COUNT(*) FROM plans WHERE active) active,
                (SELECT COUNT(*) FROM orders) orders,
                (SELECT COUNT(*) FROM orders WHERE status='pending') pending,
                (SELECT COUNT(*) FROM orders WHERE status='approved') approved,
                (SELECT COUNT(*) FROM users) users
            """)
            counts = q.fetchone()
            q.execute("SELECT * FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 10")
            recent = q.fetchall()

    return page('''
        <h1>Dashboard</h1>
        <div class="grid">
        {% for k,v in counts.items() %}
        <div class="card"><div class="muted">{{k.title()}}</div>
        <div class="big">{{v}}</div></div>
        {% endfor %}
        </div>
        <div class="card"><h2>Recent pending payments</h2>
        <div class="table"><table>
        <tr><th>Order</th><th>User</th><th>Plan</th><th>Amount</th></tr>
        {% for o in recent %}
        <tr><td>#{{o.id}}</td><td>{{o.telegram_user_id}}</td>
        <td>{{o.plan_name}}</td><td>₹{{o.amount}}</td></tr>
        {% else %}
        <tr><td colspan="4">Pending orders nahi hain.</td></tr>
        {% endfor %}
        </table></div></div>
    ''', counts=counts, recent=recent)


@app.route('/plans')
@login_required
def plans():
    with connect() as c:
        with c.cursor() as q:
            q.execute('SELECT * FROM plans ORDER BY sort_order,id')
            rows = q.fetchall()

    return page('''
        <div class="row"><h1>Plans</h1>
        <a class="btn primary" href="{{url_for('edit_plan')}}">+ Add plan</a></div>
        <div class="card table"><table>
        <tr><th>ID</th><th>Name</th><th>Price</th><th>Active</th><th>Actions</th></tr>
        {% for p in rows %}
        <tr><td>{{p.id}}</td><td>{{p.name}}</td><td>₹{{p.price}}</td>
        <td>{{p.active}}</td><td>
        <a class="btn" href="{{url_for('edit_plan',pid=p.id)}}">Edit</a>
        <a class="btn" href="{{url_for('demos',pid=p.id)}}">Demos</a>
        </td></tr>
        {% else %}
        <tr><td colspan="5">Plans abhi nahi hain. Bot DATABASE_URL ke saath start hote waqt existing plans seed karega.</td></tr>
        {% endfor %}
        </table></div>
    ''', rows=rows)


@app.route('/plan/edit', defaults={'pid': None}, methods=['GET', 'POST'])
@app.route('/plan/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def edit_plan(pid):
    with connect() as c:
        with c.cursor() as q:
            p = None
            if pid:
                q.execute('SELECT * FROM plans WHERE id=%s', (pid,))
                p = q.fetchone()

            if request.method == 'POST':
                vals = (
                    request.form.get('name', '').strip(),
                    request.form.get('price', '0').strip(),
                    request.form.get('validity', ''),
                    request.form.get('videos', ''),
                    request.form.get('image', '').strip(),
                    request.form.get('qr', '').strip(),
                    request.form.get('caption', ''),
                    'active' in request.form,
                    int(request.form.get('sort_order') or 0)
                )

                if not vals[0]:
                    flash('Plan name required.')
                    return redirect(request.url)

                if pid:
                    q.execute(
                        '''UPDATE plans SET name=%s,price=%s,validity=%s,videos=%s,
                        image=%s,qr=%s,caption=%s,active=%s,sort_order=%s WHERE id=%s''',
                        vals + (pid,)
                    )
                else:
                    q.execute(
                        '''INSERT INTO plans(name,price,validity,videos,image,qr,caption,active,sort_order)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        vals
                    )

                flash('Plan saved.')
                return redirect(url_for('plans'))

    return page('''
        <h1>{{'Edit' if p else 'Add'}} plan</h1>
        <form class="card" method="post">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <label>Name</label><input name="name" required value="{{p.name if p else ''}}">
        <label>Price</label><input name="price" required value="{{p.price if p else '0'}}">
        <label>Validity</label><input name="validity" value="{{p.validity if p else '180 days'}}">
        <label>Videos</label><input name="videos" value="{{p.videos if p else ''}}">
        <label>Image URL or Telegram file ID</label><input name="image" value="{{p.image if p else ''}}">
        <label>QR URL or Telegram file ID</label><input name="qr" value="{{p.qr if p else ''}}">
        <label>Description</label><textarea name="caption">{{p.caption if p else ''}}</textarea>
        <label>Sort order</label><input type="number" name="sort_order" value="{{p.sort_order if p else 0}}">
        <label><input class="check" type="checkbox" name="active" {% if not p or p.active %}checked{% endif %}> Active</label>
        <button class="primary">Save</button>
        <a class="btn" href="{{url_for('plans')}}">Cancel</a>
        </form>
    ''', p=p)


@app.route('/demos/<int:pid>', methods=['GET', 'POST'])
@login_required
def demos(pid):
    with connect() as c:
        with c.cursor() as q:
            q.execute('SELECT * FROM plans WHERE id=%s', (pid,))
            p = q.fetchone()
            if not p:
                abort(404)

            if request.method == 'POST':
                typ = request.form.get('media_type', 'video')
                mid = request.form.get('media_id', '').strip()
                url = request.form.get('media_url', '').strip()

                if typ not in ('video', 'photo', 'document'):
                    typ = 'video'

                if not mid and not url:
                    flash('File ID ya URL do.')
                elif url and not url.startswith(('https://', 'http://')):
                    flash('URL http(s) hona chahiye.')
                else:
                    q.execute(
                        '''INSERT INTO demos(plan_id,media_type,media_id,media_url,title,sort_order)
                        VALUES(%s,%s,%s,%s,%s,%s)''',
                        (
                            pid, typ, mid, url,
                            request.form.get('title', ''),
                            int(request.form.get('sort_order') or 0)
                        )
                    )
                    flash('Demo add ho gaya.')

                return redirect(url_for('demos', pid=pid))

            q.execute('SELECT * FROM demos WHERE plan_id=%s ORDER BY sort_order,id', (pid,))
            rows = q.fetchall()

    return page('''
        <h1>Demos: {{p.name}}</h1>
        <form class="card" method="post">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <label>Type</label>
        <select name="media_type"><option>video</option><option>photo</option><option>document</option></select>
        <label>Telegram file ID (optional)</label><input name="media_id">
        <label>Hosted media URL</label><input name="media_url" placeholder="https://.../video.mp4 or public watch page">
        <label>Title</label><input name="title">
        <label>Sort order</label><input type="number" name="sort_order" value="0">
        <button class="primary">Add demo</button>
        </form>
        <div class="card">
        {% for d in rows %}
        <div class="row"><div><b>#{{d.id}} · {{d.media_type}}</b><br>
        <small>{{d.media_id or d.media_url}}</small></div>
        <form method="post" action="{{url_for('delete_demo',did=d.id)}}">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <button class="danger">Delete</button></form></div><hr>
        {% else %}No demos yet.{% endfor %}
        </div>
    ''', p=p, rows=rows)


@app.post('/demo/delete/<int:did>')
@login_required
def delete_demo(did):
    with connect() as c:
        with c.cursor() as q:
            q.execute('DELETE FROM demos WHERE id=%s RETURNING plan_id', (did,))
            r = q.fetchone()

    return redirect(url_for('demos', pid=r['plan_id'])) if r else redirect(url_for('plans'))


@app.route('/orders')
@login_required
def orders():
    status = request.args.get('status', 'pending')
    allowed = ('pending', 'approved', 'rejected', 'all')

    if status not in allowed:
        status = 'pending'

    with connect() as c:
        with c.cursor() as q:
            if status == 'all':
                q.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 500')
            else:
                q.execute('SELECT * FROM orders WHERE status=%s ORDER BY id DESC LIMIT 500', (status,))
            rows = q.fetchall()

    return page('''
        <h1>Payment orders</h1>
        <nav>{% for s in ['pending','approved','rejected','all'] %}
        <a href="{{url_for('orders',status=s)}}">{{s.title()}}</a>{% endfor %}</nav>
        <div class="card table"><table>
        <tr><th>Order</th><th>User</th><th>Plan/amount</th><th>Screenshot</th><th>Status/review</th></tr>
        {% for o in rows %}
        <tr><td>#{{o.id}}<br><small>{{o.created_at}}</small></td>
        <td>{{o.telegram_user_id}}</td><td>{{o.plan_name}}<br>₹{{o.amount}}</td>
        <td><small>{{o.screenshot_file_id}}</small></td><td>{{o.status}}
        {% if o.status=='pending' %}
        <form method="post" action="{{url_for('review_order',oid=o.id)}}">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <input name="note" placeholder="Note">
        <button name="action" value="approved" class="primary">Approve</button>
        <button name="action" value="rejected" class="danger">Reject</button>
        </form>
        {% else %}<br>{{o.admin_note}}{% endif %}</td></tr>
        {% else %}<tr><td colspan="5">No orders.</td></tr>{% endfor %}
        </table></div>
    ''', rows=rows)


@app.post('/order/review/<int:oid>')
@login_required
def review_order(oid):
    action = request.form.get('action')

    if action not in ('approved', 'rejected'):
        abort(400)

    with connect() as c:
        with c.cursor() as q:
            q.execute(
                '''UPDATE orders SET status=%s,reviewed_at=NOW(),admin_note=%s
                WHERE id=%s RETURNING *''',
                (action, request.form.get('note', ''), oid)
            )
            o = q.fetchone()

    if not o:
        abort(404)

    ok, detail = notify(
        o['telegram_user_id'],
        f"Order #{oid} ({o['plan_name']}, ₹{o['amount']}) {action}."
    )

    flash('Order ' + action + ('. User notified.' if ok else '. Telegram notification failed: ' + detail))
    return redirect(url_for('orders', status='pending'))


@app.route('/users')
@login_required
def users():
    with connect() as c:
        with c.cursor() as q:
            q.execute('SELECT * FROM users ORDER BY last_seen DESC LIMIT 500')
            rows = q.fetchall()

    return page('''
        <h1>Telegram users</h1>
        <div class="card table"><table>
        <tr><th>ID</th><th>Name</th><th>Username</th><th>Last seen</th></tr>
        {% for u in rows %}
        <tr><td>{{u.telegram_user_id}}</td><td>{{u.first_name}}</td>
        <td>{{u.username}}</td><td>{{u.last_seen}}</td></tr>
        {% else %}<tr><td colspan="4">Users nahi hain.</td></tr>{% endfor %}
        </table></div>
    ''', rows=rows)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        t = request.form.get('bot_token', '').strip()
        s = request.form.get('support_link', '').strip()

        if t and ':' not in t:
            flash('Bot token format check karo.')
            return redirect(url_for('settings'))

        if t:
            set_setting('bot_token', t)

        if not s.startswith(('https://t.me/', 'https://telegram.me/')):
            flash('Valid Telegram support link do.')
            return redirect(url_for('settings'))

        set_setting('support_link', s)
        flash('Settings saved. Support link bot home par use hoga. Token changes ke baad bot restart karna zaroori hai.')
        return redirect(url_for('settings'))

    return page('''
        <h1>Settings</h1>
        <form class="card" method="post">
        <input type="hidden" name="csrf_token" value="{{csrf_token()}}">
        <p>Saved token: {{'Yes' if token_set else 'No'}}</p>
        <label>Bot token (optional)</label><input type="password" name="bot_token">
        <label>Support link</label><input name="support_link" value="{{support}}">
        <button class="primary">Save</button>
        </form>
    ''', token_set=bool(token()), support=setting('support_link', 'https://t.me/xylerigcc'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False)
