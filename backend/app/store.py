import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, value TEXT NOT NULL,
                    source_message_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, key TEXT NOT NULL,
                    value TEXT NOT NULL, evidence TEXT NOT NULL, source_message_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0
                );
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
            if 'metadata' not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            db.execute("UPDATE messages SET status='interrupted', content=CASE WHEN content='' THEN '回复因服务重启而中断。' ELSE content END WHERE status='streaming'")

    def list_conversations(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM conversations ORDER BY updated_at DESC')]

    def create_conversation(self):
        record = {'id': str(uuid4()), 'title': '新的对话', 'created_at': now(), 'updated_at': now()}
        with self.connect() as db:
            db.execute('INSERT INTO conversations VALUES (:id,:title,:created_at,:updated_at)', record)
        return record

    def get_conversation(self, conversation_id: str):
        with self.connect() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
            return dict(row) if row else None

    def messages(self, conversation_id: str):
        with self.connect() as db:
            records = [dict(row) for row in db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY rowid', (conversation_id,))]
            for record in records:
                metadata = json.loads(record.pop('metadata', '{}'))
                record.update({'sources': metadata.get('sources', []), 'tools': metadata.get('tools', [])})
            return records

    def add_message(self, conversation_id: str, role: str, content: str, status: str = 'complete', metadata=None):
        record = {'id': str(uuid4()), 'conversation_id': conversation_id, 'role': role, 'content': content, 'status': status, 'created_at': now()}
        with self.connect() as db:
            db.execute('INSERT INTO messages (id,conversation_id,role,content,status,created_at,metadata) VALUES (:id,:conversation_id,:role,:content,:status,:created_at,:metadata)', {**record, 'metadata': json.dumps(metadata or {}, ensure_ascii=False)})
            if role == 'user':
                db.execute("UPDATE conversations SET title=CASE WHEN title='新的对话' THEN ? ELSE title END, updated_at=? WHERE id=?", (content[:24], now(), conversation_id))
            else:
                db.execute('UPDATE conversations SET updated_at=? WHERE id=?', (now(), conversation_id))
        return {**record, **(metadata or {})}

    def update_message(self, message_id, content, status, metadata=None):
        with self.connect() as db:
            db.execute('UPDATE messages SET content=?,status=?,metadata=? WHERE id=?', (content, status, json.dumps(metadata or {}, ensure_ascii=False), message_id))
            row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
            record = dict(row)
            record.pop('metadata', None)
            return {**record, **(metadata or {})}

    def list_memories(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM memories ORDER BY updated_at DESC')]

    def add_candidates(self, conversation_id, items):
        records = []
        with self.connect() as db:
            for item in items[:30]:
                record = {**item, 'id': str(uuid4()), 'conversation_id': conversation_id, 'created_at': now()}
                db.execute('INSERT INTO memory_candidates(id,conversation_id,key,value,evidence,source_message_id,created_at) VALUES(:id,:conversation_id,:key,:value,:evidence,:source_message_id,:created_at)', record)
                old = db.execute('SELECT value FROM memories WHERE key=?', (record['key'],)).fetchone()
                record['existing_value'] = old['value'] if old else None
                records.append(record)
        return records

    def confirm_candidates(self, items):
        saved = []
        with self.connect() as db:
            # Whole selection is atomic; unknown/reused candidate cannot partially save.
            for item in items:
                candidate = db.execute('SELECT * FROM memory_candidates WHERE id=? AND confirmed=0', (item['id'],)).fetchone()
                if not candidate:
                    raise ValueError('候选记忆不存在或已经确认，请重新总结。')
                existing = db.execute('SELECT * FROM memories WHERE key=?', (item['key'],)).fetchone()
                record = {'id': existing['id'] if existing else str(uuid4()), 'key': item['key'], 'value': item['value'], 'source_message_id': candidate['source_message_id'], 'created_at': existing['created_at'] if existing else now(), 'updated_at': now()}
                db.execute('INSERT INTO memories VALUES(:id,:key,:value,:source_message_id,:created_at,:updated_at) ON CONFLICT(key) DO UPDATE SET value=excluded.value,source_message_id=excluded.source_message_id,updated_at=excluded.updated_at', record)
                db.execute('UPDATE memory_candidates SET confirmed=1 WHERE id=?', (item['id'],))
                saved.append(record)
        return saved

    def edit_memory(self, memory_id, value):
        with self.connect() as db:
            result = db.execute('UPDATE memories SET value=?,source_message_id=NULL,updated_at=? WHERE id=?', (value, now(), memory_id))
            if result.rowcount != 1:
                raise ValueError('记忆不存在')
            return dict(db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone())

    def delete_memory(self, memory_id):
        with self.connect() as db:
            result = db.execute('DELETE FROM memories WHERE id=?', (memory_id,))
            return result.rowcount == 1
