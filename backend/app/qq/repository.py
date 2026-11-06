import hashlib
import json
import re
import time
from pathlib import Path
from threading import RLock

from ..credentials import decrypt_secret, encrypt_secret
from ..store import Store
from .models import Connection, Policy


def identifier(value):
    value = str(value)
    if not re.fullmatch(r'\d{5,20}', value):
        raise ValueError('QQ 账号或群 ID 无效')
    return value


class QQRepository(Store):
    def __init__(self, root: Path):
        self.scope_lock = RLock()
        self.root = root
        super().__init__(root / 'qq.sqlite3')
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policies(kind TEXT, target TEXT, value TEXT NOT NULL,
                    since REAL NOT NULL, next_due REAL, cursor REAL, PRIMARY KEY(kind,target));
                CREATE TABLE IF NOT EXISTS peers(kind TEXT,target TEXT,name TEXT,PRIMARY KEY(kind,target));
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,bot TEXT,kind TEXT,target TEXT,
                    author TEXT,name TEXT,stamp REAL,text TEXT,segments TEXT,state TEXT,error TEXT DEFAULT '',
                    reply TEXT DEFAULT '', conversation TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS event_range ON events(bot,kind,target,stamp);
                CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,event TEXT,signature TEXT DEFAULT '',
                    data BLOB,description TEXT DEFAULT '',error TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS summaries(id TEXT PRIMARY KEY,bot TEXT,target TEXT,start REAL,end REAL,
                    delivery TEXT,state TEXT,content TEXT DEFAULT '',error TEXT DEFAULT '',sent TEXT DEFAULT 'pending',
                    created REAL, UNIQUE(bot,target,start,end));
                CREATE TABLE IF NOT EXISTS scopes(key TEXT PRIMARY KEY,conversation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS manual_profiles(bot TEXT,kind TEXT,target TEXT,subject TEXT,
                    revision INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(bot,kind,target,subject));
                CREATE TABLE IF NOT EXISTS gaps(start REAL,end REAL,reason TEXT);
                CREATE TABLE IF NOT EXISTS replies(bot TEXT,kind TEXT,target TEXT,natural INTEGER,stamp REAL);
            """)

            fields = {row['name'] for row in db.execute('PRAGMA table_info(summaries)')}
            if 'automatic' not in fields:
                db.execute('ALTER TABLE summaries ADD COLUMN automatic INTEGER NOT NULL DEFAULT 0')
            if 'recipient' not in fields:
                db.execute("ALTER TABLE summaries ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
            if 'profile_revision' not in fields:
                db.execute('ALTER TABLE summaries ADD COLUMN profile_revision INTEGER NOT NULL DEFAULT 0')
            if 'attempts' not in {row['name'] for row in db.execute('PRAGMA table_info(images)')}:
                db.execute('ALTER TABLE images ADD COLUMN attempts INTEGER NOT NULL DEFAULT 1')
            if 'reply_sticker' not in {row['name'] for row in db.execute('PRAGMA table_info(events)')}:
                db.execute("ALTER TABLE events ADD COLUMN reply_sticker TEXT NOT NULL DEFAULT 'null'")

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def connection(self, secret=False):
        raw = self.get('connection', Connection().model_dump())
        encrypted = raw.pop('token_encrypted', '')
        raw['token'] = decrypt_secret(encrypted) if encrypted and secret else ''
        return Connection(**raw)

    def save_connection(self, value):
        old = self.get('connection', {})
        raw = value.model_dump(exclude={'token'})
        raw['token_encrypted'] = encrypt_secret(value.token) if value.token else old.get('token_encrypted', '')
        if value.enabled and (not value.bot_id or not raw['token_encrypted']):
            raise ValueError('启用前须填写机器人 QQ 号及 OneBot Token')
        # Policies and identity must not accidentally transfer to another bot account.
        if old.get('bot_id') and old['bot_id'] != value.bot_id:
            raise ValueError('本版固定一个机器人账号；请使用原账号或独立数据目录')
        self.put('connection', raw)

    def policy(self, kind, target):
        with self.connect() as db:
            row = db.execute('SELECT value FROM policies WHERE kind=? AND target=?', (kind, target)).fetchone()
            return Policy(**json.loads(row[0])) if row else Policy()

    def save_policy(self, kind, target, policy, now=None):
        if kind not in ('group', 'private'):
            raise ValueError('未知场景')
        identifier(target)
        now = time.time() if now is None else now
        previous = self.policy(kind, target)
        from .schedule import next_due

        reset = not previous.collect or any(
            getattr(previous, field) != getattr(policy, field)
            for field in ('schedule', 'daily_time', 'interval_hours', 'window', 'window_start', 'window_end')
        )
        with self.connect() as db:
            db.execute(
                """INSERT INTO policies VALUES (?,?,?,?,?,?)
                ON CONFLICT(kind,target) DO UPDATE SET value=excluded.value,
                since=CASE WHEN ? THEN excluded.since ELSE policies.since END,
                next_due=CASE WHEN ? THEN excluded.next_due ELSE policies.next_due END,
                cursor=CASE WHEN ? THEN excluded.cursor ELSE policies.cursor END""",
                (
                    kind,
                    target,
                    policy.model_dump_json(),
                    now,
                    next_due(policy, now),
                    now,
                    not previous.collect,
                    reset,
                    reset,
                ),
            )
        if not policy.collect:
            with self.connect() as db:
                db.execute(
                    "UPDATE events SET state='skipped' WHERE kind=? AND target=? AND state='queued'", (kind, target)
                )

    def policies(self):
        with self.connect() as db:
            result = []
            for row in db.execute('SELECT * FROM policies'):
                last = db.execute(
                    'SELECT state,error,end FROM summaries WHERE target=? ORDER BY created DESC LIMIT 1',
                    (row['target'],),
                ).fetchone()
                skipped = db.execute('SELECT value FROM settings WHERE key=?', ('skipped:' + row['target'],)).fetchone()
                result.append(
                    {
                        **dict(row),
                        'policy': json.loads(row['value']),
                        'last_summary': dict(last) if last else None,
                        'skipped': json.loads(skipped[0]) if skipped else 0,
                    }
                )
            return result

    def peers(self, kind):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM peers WHERE kind=? ORDER BY name,target', (kind,))]

    def save_peers(self, kind, items):
        with self.connect() as db:
            db.execute('DELETE FROM peers WHERE kind=?', (kind,))
            for item in items:
                target = identifier(item['group_id' if kind == 'group' else 'user_id'])
                name = str(item.get('group_name') or item.get('remark') or item.get('nickname') or target)[:200]
                db.execute('INSERT OR REPLACE INTO peers VALUES (?,?,?)', (kind, target, name))

    def capture(self, event):
        if event.get('post_type') != 'message' or event.get('message_type') not in ('private', 'group'):
            return None
        bot, author = identifier(event.get('self_id')), identifier(event.get('user_id'))
        expected = self.connection().bot_id
        if (expected and bot != expected) or bot == author:
            return None
        kind = event['message_type']
        target = identifier(event.get('group_id') if kind == 'group' else author)
        if not self.policy(kind, target).collect:
            return None
        stamp = float(event['time'])
        if not 0 < stamp <= time.time() + 300:
            return None
        if stamp < time.time() - self.connection().retention_days * 86400:
            return None
        segments = event.get('message')
        if not isinstance(segments, list) or len(segments) > 100:
            raise ValueError('请在 OneBot 中设置 array 消息格式')
        safe, texts = [], []
        for item in segments:
            if not isinstance(item, dict) or not isinstance(item.get('data'), dict):
                continue
            typ, data = item.get('type'), item['data']
            if typ == 'text':
                text = str(data.get('text', ''))[:6000]
                texts.append(text)
                safe.append({'type': 'text', 'data': {'text': text}})
            elif typ == 'at':
                safe.append({'type': 'at', 'data': {'qq': str(data.get('qq', ''))[:20]}})
            elif typ == 'image':
                safe.append({'type': 'image', 'data': {'url': str(data.get('url', ''))[:2048]}})
                texts.append('[图片，尚未识别]')
            elif typ == 'face':
                from .faces import label

                face_id = str(data.get('id', ''))
                if re.fullmatch(r'[0-9]{1,5}', face_id):
                    face_id = str(int(face_id))
                    safe.append({'type': 'face', 'data': {'id': face_id}})
                    texts.append(label(face_id))
                else:
                    texts.append('[QQ表情：编号无法解析]')
            else:
                texts.append(f'[{str(typ)[:30]} 未解析]')
        text = ''.join(texts)[:6000]
        # A short OneBot id alone is not durable: include scene, author, source time and payload digest.
        stable = event.get('message_seq') or event.get('real_id') or event.get('message_id')
        identity = [
            bot,
            kind,
            target,
            author,
            stable,
            stamp,
            [item if item['type'] != 'image' else {'type': 'image'} for item in safe],
        ]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        sender = event.get('sender')
        sender = sender if isinstance(sender, dict) else {}
        name = str(sender.get('card') or sender.get('nickname') or author)[:100]
        with self.connect() as db:
            if db.execute("SELECT count(*) FROM events WHERE state='queued'").fetchone()[0] >= 1000:
                raise ValueError('QQ 处理队列已满，暂停接收；请检查模型及群设置')
            inserted = db.execute(
                'INSERT OR IGNORE INTO events(id,bot,kind,target,author,name,stamp,text,segments,state) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (key, bot, kind, target, author, name, stamp, text, json.dumps(safe), 'queued'),
            ).rowcount
        return self.event(key) if inserted else None

    def event(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM events WHERE id=?', (key,)).fetchone()
            return dict(row) if row else None

    def events(self, state, limit=50):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute('SELECT * FROM events WHERE state=? ORDER BY stamp,id LIMIT ?', (state, limit))
            ]

    def event_state(self, key, state, error='', reply='', conversation=''):
        with self.connect() as db:
            db.execute(
                'UPDATE events SET state=?,error=?,reply=?,conversation=? WHERE id=?',
                (state, error, reply, conversation, key),
            )

    def messages(self, bot, kind, target, start, end, limit=20001, newest=False):
        with self.connect() as db:
            order = 'stamp DESC,id DESC' if newest else 'stamp,id'
            result = [
                dict(row)
                for row in db.execute(
                    'SELECT * FROM events WHERE bot=? AND kind=? AND target=? '
                    f'AND stamp>=? AND stamp<? ORDER BY {order} LIMIT ?',
                    (bot, kind, target, start, end, limit),
                )
            ]
            return result[::-1] if newest else result

    def reserve_reply(self, event, natural, now):
        if now - event['stamp'] > 300:
            return False
        with self.connect() as db:
            recent = db.execute(
                'SELECT stamp FROM replies WHERE bot=? AND kind=? AND target=? AND stamp>? '
                'AND (?=0 OR natural=1) ORDER BY stamp DESC',
                (event['bot'], event['kind'], event['target'], now - 3600, int(natural)),
            ).fetchall()
        cooldown, maximum = (120, 10) if natural else (3, 60)
        return len(recent) < maximum and (not recent or now - recent[0]['stamp'] >= cooldown)

    def record_sent(self, event, natural, stamp):
        with self.connect() as db:
            db.execute(
                'INSERT INTO replies VALUES (?,?,?,?,?)',
                (event['bot'], event['kind'], event['target'], int(natural), stamp),
            )

    def queue_summary(self, target, start, end, delivery='panel', automatic=False):
        identifier(target)
        connection = self.connection()
        if not connection.bot_id:
            raise ValueError('请先保存机器人 QQ 号')
        policy = self.policy('group', target)
        if not policy.collect:
            raise ValueError('该群尚未启用采集')
        if delivery == 'group' and not policy.allow_group_send:
            raise ValueError('该群未允许摘要发送')
        if delivery == 'owner' and not self.get('owner'):
            raise ValueError('请先绑定主人 QQ')
        key = hashlib.sha256(f'{connection.bot_id}:{target}:{start:.6f}:{end:.6f}'.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                'INSERT OR IGNORE INTO summaries(id,bot,target,start,end,delivery,state,created,automatic,recipient) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (
                    key,
                    connection.bot_id,
                    target,
                    start,
                    end,
                    delivery,
                    'queued',
                    time.time(),
                    int(automatic),
                    self.get('owner', '') if delivery == 'owner' else target,
                ),
            )
        getattr(self, 'notify', lambda: None)()
        return self.summary(key)

    def summary(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM summaries WHERE id=?', (key,)).fetchone()
            return dict(row) if row else None

    def summaries(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM summaries ORDER BY created DESC LIMIT 200')]

    def next_summary(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM summaries WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            return dict(row) if row else None

    def summary_state(self, key, state, content='', error=''):
        with self.connect() as db:
            db.execute('UPDATE summaries SET state=?,content=?,error=? WHERE id=?', (state, content, error, key))
        if state == 'queued':
            getattr(self, 'notify', lambda: None)()

    def delivery_state(self, key, state, error=''):
        with self.connect() as db:
            db.execute('UPDATE summaries SET sent=?,error=? WHERE id=?', (state, error, key))

    def delete_summary(self, key):
        with self.connect() as db:
            db.execute('DELETE FROM summaries WHERE id=?', (key,))

    def schedule(self, now):
        from datetime import datetime, timedelta

        from .schedule import BEIJING, at, next_due, window

        for rule in self.policies():
            policy = Policy(**rule['policy'])
            due = rule['next_due']
            if rule['kind'] != 'group' or not policy.collect or due is None or due > now:
                continue
            if policy.schedule == 'interval':
                missed = int((now - due) // (policy.interval_hours * 3600))
                latest = due + missed * policy.interval_hours * 3600
            else:
                latest_day = at(datetime.fromtimestamp(now, BEIJING), policy.daily_time)
                if latest_day.timestamp() > now:
                    latest_day -= timedelta(days=1)
                latest = latest_day.timestamp()
                missed = max(0, int((latest - due) // 86400))
            start, end = window(policy, latest, rule['cursor'] or rule['since'])
            # Keep a stable window end while generation is running and new messages arrive.
            if end > start:
                self.queue_summary(rule['target'], max(start, end - 32 * 86400), end, policy.delivery, automatic=True)
            self.put('skipped:' + rule['target'], missed)
            with self.connect() as db:
                db.execute(
                    'UPDATE policies SET next_due=?,cursor=? WHERE kind=? AND target=?',
                    (next_due(policy, latest), end, rule['kind'], rule['target']),
                )

    def cleanup(self, now):
        with self.scope_lock:
            return self._cleanup(now)

    def _cleanup(self, now):
        from datetime import datetime, timezone

        from ..file_paths import no_link

        cutoff = now - self.connection().retention_days * 86400
        with self.connect() as db:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('DELETE FROM images WHERE event IN (SELECT id FROM events WHERE stamp<?)', (cutoff,))
            db.execute('DELETE FROM events WHERE stamp<?', (cutoff,))
            db.execute('DELETE FROM replies WHERE stamp<?', (now - 86400,))
            db.execute('DELETE FROM gaps WHERE end<?', (cutoff,))
        stamp = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        directory = self.root / 'scopes'
        if directory.exists():
            no_link(directory)
            for path in directory.glob('*.sqlite3'):
                no_link(path)
                old_scope = path.stat().st_mtime < cutoff
                # All hidden conversation copies expire too; derived facts keep no raw source copy.
                store = Store(path)
                with store.connect() as db:
                    db.execute('PRAGMA secure_delete=ON')
                    db.execute(
                        "UPDATE memory_events SET source_message_id=NULL,evidence='' WHERE source_message_id IN "
                        '(SELECT id FROM messages WHERE created_at<?)',
                        (stamp,),
                    )
                    db.execute(
                        'UPDATE memories SET source_message_id=NULL WHERE source_message_id IN '
                        '(SELECT id FROM messages WHERE created_at<?)',
                        (stamp,),
                    )
                    db.execute(
                        'DELETE FROM memory_candidates WHERE source_message_id IN '
                        '(SELECT id FROM messages WHERE created_at<?)',
                        (stamp,),
                    )
                    db.execute('DELETE FROM messages WHERE created_at<?', (stamp,))
                    db.execute("UPDATE conversations SET title='QQ 对话'")
                    retained = (
                        any(
                            db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                            for table in (
                                'messages',
                                'memories',
                                'memory_candidates',
                                'memory_events',
                                'memory_blocks',
                                'conversation_summaries',
                                'conversation_episodes',
                                'file_tasks',
                                'annotations',
                            )
                        )
                        or db.execute("SELECT 1 FROM memory_jobs WHERE status<>'idle' LIMIT 1").fetchone()
                    )
                # Existing per-migration backups must not retain expired QQ raw messages.
                backups = directory / 'backups'
                if backups.exists():
                    no_link(backups)
                    for backup in backups.glob(path.stem + '-v*.sqlite3'):
                        backup.unlink()
                if old_scope and not retained and re.fullmatch(r'[0-9a-f]{64}', path.stem):
                    with store.connect() as db:
                        db.execute('PRAGMA journal_mode=DELETE')
                    path.unlink()
                    with self.connect() as db:
                        for row in db.execute('SELECT key FROM scopes').fetchall():
                            if (
                                not row['key'].endswith(':owner')
                                and hashlib.sha256(row['key'].encode()).hexdigest() == path.stem
                            ):
                                db.execute('DELETE FROM scopes WHERE key=?', (row['key'],))

    def scopes(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM scopes ORDER BY key')]
