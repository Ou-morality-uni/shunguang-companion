import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .migrations import SCHEMA_VERSION, migrate


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
        connection.execute('PRAGMA busy_timeout=5000')
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
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError('数据库版本高于当前程序，请使用较新版本。')
            if (
                version < SCHEMA_VERSION
                and db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'").fetchone()
            ):
                backup_dir = self.path.parent / 'backups'
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / f'{self.path.stem}-v{version}-{uuid4().hex}.sqlite3'
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            db.execute('PRAGMA journal_mode=WAL')
            migrate(db)
            db.execute(
                "UPDATE messages SET status='interrupted', content=CASE WHEN content='' THEN '回复因服务重启而中断。' ELSE content END WHERE status='streaming'"
            )

    def list_conversations(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM conversations ORDER BY updated_at DESC')]

    def list_workspaces(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM workspaces ORDER BY created_at')]

    def get_workspace(self, workspace_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
            return dict(row) if row else None

    def grant_workspace(self, path, identity):
        with self.connect() as db:
            row = db.execute('SELECT id FROM workspaces WHERE path=?', (path,)).fetchone()
            workspace_id = row['id'] if row else str(uuid4())
            db.execute(
                """INSERT INTO workspaces VALUES (?,?,?,1,?)
                ON CONFLICT(path) DO UPDATE SET enabled=1,identity=excluded.identity""",
                (workspace_id, path, identity, now()),
            )
        return self.get_workspace(workspace_id)

    def revoke_workspace(self, workspace_id):
        with self.connect() as db:
            return db.execute('UPDATE workspaces SET enabled=0 WHERE id=?', (workspace_id,)).rowcount == 1

    def create_file_task(self, workspace_id, title, steps, status):
        task_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                'INSERT INTO file_tasks VALUES (?,?,?,?,?,?,?,?)',
                (task_id, workspace_id, title, status, json.dumps(steps, ensure_ascii=False), '', now(), now()),
            )
        return self.get_file_task(task_id)

    def get_file_task(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM file_tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                return None
            record = dict(row)
            record['steps'] = json.loads(record['steps'])
            return record

    def list_file_tasks(self, limit=50):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM file_tasks ORDER BY created_at DESC LIMIT ?', (limit,))
            return [{**dict(row), 'steps': json.loads(row['steps'])} for row in rows]

    def save_file_task(self, record):
        record['updated_at'] = now()
        with self.connect() as db:
            db.execute(
                'UPDATE file_tasks SET status=?,steps=?,error=?,updated_at=? WHERE id=?',
                (
                    record['status'],
                    json.dumps(record['steps'], ensure_ascii=False),
                    record['error'],
                    record['updated_at'],
                    record['id'],
                ),
            )

    def interrupt_file_tasks(self):
        with self.connect() as db:
            db.execute(
                "UPDATE file_tasks SET status='interrupted',error=?,updated_at=? WHERE status IN ('queued','running','restoring')",
                ('服务已重启。请检查操作记录，按需恢复；不会自动重放文件操作。', now()),
            )

    def create_conversation(self):
        record = {'id': str(uuid4()), 'title': '新的对话', 'created_at': now(), 'updated_at': now()}
        with self.connect() as db:
            db.execute('INSERT INTO conversations VALUES (:id,:title,:created_at,:updated_at)', record)
        return record

    def begin_turn(self, conversation_id: str | None, content: str):
        with self.connect() as db:
            if conversation_id is None:
                conversation_id = str(uuid4())
                db.execute('INSERT INTO conversations VALUES (?,?,?,?)', (conversation_id, content[:24], now(), now()))
            record = {
                'id': str(uuid4()),
                'conversation_id': conversation_id,
                'role': 'user',
                'content': content,
                'status': 'complete',
                'created_at': now(),
            }
            db.execute(
                'INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (:id,:conversation_id,:role,:content,:status,:created_at)',
                record,
            )
            db.execute(
                "UPDATE conversations SET title=CASE WHEN title='新的对话' THEN ? ELSE title END, updated_at=? WHERE id=?",
                (content[:24], now(), conversation_id),
            )
            return record

    def delete_conversation(self, conversation_id: str):
        with self.connect() as db:
            # Confirmed facts survive; provenance is explicitly detached. Unconfirmed candidates do not.
            db.execute(
                'UPDATE memories SET source_message_id=NULL WHERE source_message_id IN (SELECT id FROM messages WHERE conversation_id=?)',
                (conversation_id,),
            )
            db.execute('DELETE FROM memory_candidates WHERE conversation_id=?', (conversation_id,))
            return db.execute('DELETE FROM conversations WHERE id=?', (conversation_id,)).rowcount == 1

    def get_conversation(self, conversation_id: str):
        with self.connect() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
            return dict(row) if row else None

    def messages(self, conversation_id: str, limit: int | None = None, before: int | None = None):
        with self.connect() as db:
            query = 'SELECT * FROM messages WHERE conversation_id=?'
            params = [conversation_id]
            if before is not None:
                query += ' AND seq < ?'
                params.append(before)
            query += ' ORDER BY seq DESC'
            if limit is not None:
                query += ' LIMIT ?'
                params.append(limit)
            records = [dict(row) for row in db.execute(query, params)][::-1]
            for record in records:
                metadata = json.loads(record.pop('metadata', '{}'))
                record.update(
                    {
                        'sources': metadata.get('sources', []),
                        'context_sources': metadata.get('context_sources', []),
                        'tools': metadata.get('tools', []),
                        'sticker': metadata.get('sticker'),
                    }
                )
            return records

    def add_message(self, conversation_id: str, role: str, content: str, status: str = 'complete', metadata=None):
        record = {
            'id': str(uuid4()),
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            'status': status,
            'created_at': now(),
        }
        with self.connect() as db:
            db.execute(
                'INSERT INTO messages (id,conversation_id,role,content,status,created_at,metadata) VALUES (:id,:conversation_id,:role,:content,:status,:created_at,:metadata)',
                {**record, 'metadata': json.dumps(metadata or {}, ensure_ascii=False)},
            )
            if role == 'user':
                db.execute(
                    "UPDATE conversations SET title=CASE WHEN title='新的对话' THEN ? ELSE title END, updated_at=? WHERE id=?",
                    (content[:24], now(), conversation_id),
                )
            else:
                db.execute('UPDATE conversations SET updated_at=? WHERE id=?', (now(), conversation_id))
        return {**record, **(metadata or {})}

    def update_message(self, message_id, content, status, metadata=None):
        with self.connect() as db:
            db.execute(
                'UPDATE messages SET content=?,status=?,metadata=? WHERE id=?',
                (content, status, json.dumps(metadata or {}, ensure_ascii=False), message_id),
            )
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
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM conversations WHERE id=?', (conversation_id,)).fetchone():
                raise ValueError('来源对话已删除，请重新选择对话。')
            for item in items[:30]:
                if db.execute(
                    'SELECT 1 FROM forgotten_messages WHERE message_id=?', (item['source_message_id'],)
                ).fetchone():
                    continue
                source = db.execute(
                    'SELECT seq,content FROM messages WHERE id=?', (item['source_message_id'],)
                ).fetchone()
                if (
                    not source
                    or db.execute(
                        'SELECT 1 FROM memory_blocks WHERE value=? AND through_seq>=?', (item['value'], source['seq'])
                    ).fetchone()
                ):
                    continue
                record = {**item, 'id': str(uuid4()), 'conversation_id': conversation_id, 'created_at': now()}
                db.execute(
                    'INSERT INTO memory_candidates(id,conversation_id,key,value,evidence,source_message_id,created_at) VALUES(:id,:conversation_id,:key,:value,:evidence,:source_message_id,:created_at)',
                    record,
                )
                old = db.execute('SELECT value FROM memories WHERE key=?', (record['key'],)).fetchone()
                record['existing_value'] = old['value'] if old else None
                records.append(record)
        return records

    def confirm_candidates(self, items):
        saved = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Whole selection is atomic; unknown/reused candidate cannot partially save.
            for item in items:
                candidate = db.execute(
                    'SELECT * FROM memory_candidates WHERE id=? AND confirmed=0', (item['id'],)
                ).fetchone()
                if not candidate:
                    raise ValueError('候选记忆不存在或已经确认，请重新总结。')
                source = db.execute('SELECT seq FROM messages WHERE id=?', (candidate['source_message_id'],)).fetchone()
                if (
                    not source
                    or db.execute(
                        'SELECT 1 FROM memory_blocks WHERE value=? AND through_seq>=?', (item['value'], source['seq'])
                    ).fetchone()
                ):
                    raise ValueError('此候选来自已忘记的内容，请用新的用户消息明确重新保存。')
                if db.execute(
                    'SELECT 1 FROM forgotten_messages WHERE message_id=?', (candidate['source_message_id'],)
                ).fetchone():
                    raise ValueError('此候选来自已忘记的消息。')
                existing = db.execute('SELECT * FROM memories WHERE key=?', (item['key'],)).fetchone()
                record = {
                    'id': existing['id'] if existing else str(uuid4()),
                    'key': item['key'],
                    'value': item['value'],
                    'source_message_id': candidate['source_message_id'],
                    'created_at': existing['created_at'] if existing else now(),
                    'updated_at': now(),
                }
                db.execute(
                    'INSERT INTO memories VALUES(:id,:key,:value,:source_message_id,:created_at,:updated_at) ON CONFLICT(key) DO UPDATE SET value=excluded.value,source_message_id=excluded.source_message_id,updated_at=excluded.updated_at',
                    record,
                )
                db.execute('UPDATE memory_candidates SET confirmed=1 WHERE id=?', (item['id'],))
                saved.append(record)
        return saved

    def edit_memory(self, memory_id, value):
        with self.connect() as db:
            previous = db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone()
            if previous and previous['value'] != value:
                self._block(db, previous['key'], previous['value'], previous['source_message_id'])
            result = db.execute(
                'UPDATE memories SET value=?,source_message_id=NULL,updated_at=? WHERE id=?', (value, now(), memory_id)
            )
            if result.rowcount != 1:
                raise ValueError('记忆不存在')
            return dict(db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone())

    def delete_memory(self, memory_id):
        with self.connect() as db:
            previous = db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone()
            if previous:
                self._block(db, previous['key'], previous['value'], previous['source_message_id'])
            result = db.execute('DELETE FROM memories WHERE id=?', (memory_id,))
            return result.rowcount == 1

    @staticmethod
    def _block(db, key, value, source_message_id=None):
        boundary = db.execute('SELECT COALESCE(MAX(seq),0) FROM messages').fetchone()[0]
        db.execute(
            'INSERT INTO memory_blocks VALUES(?,?,?) ON CONFLICT(key,value) DO UPDATE SET through_seq=excluded.through_seq',
            (key, value, boundary),
        )
        db.execute('DELETE FROM conversation_summaries')
        source = db.execute('SELECT * FROM messages WHERE id=?', (source_message_id,)).fetchone()
        if source:
            following = db.execute(
                "SELECT MIN(seq) FROM messages WHERE conversation_id=? AND role='user' AND seq>?",
                (source['conversation_id'], source['seq']),
            ).fetchone()[0]
            ids = db.execute(
                'SELECT id FROM messages WHERE conversation_id=? AND seq>=? AND seq<?',
                (source['conversation_id'], source['seq'], following or boundary + 1),
            ).fetchall()
            db.executemany('INSERT OR IGNORE INTO forgotten_messages VALUES(?)', [(row['id'],) for row in ids])

    def save_fact(self, key, value, evidence, source_message_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            source = db.execute(
                "SELECT * FROM messages WHERE id=? AND role='user' AND status='complete'", (source_message_id,)
            ).fetchone()
            if (
                not source
                or evidence not in source['content']
                or value not in evidence
                or db.execute('SELECT 1 FROM forgotten_messages WHERE message_id=?', (source_message_id,)).fetchone()
            ):
                raise ValueError('没有可核对的用户原话')
            if db.execute(
                'SELECT 1 FROM memory_blocks WHERE key=? AND value=? AND through_seq>=?', (key, value, source['seq'])
            ).fetchone():
                raise ValueError('此来源已被用户要求忘记')
            old = db.execute('SELECT * FROM memories WHERE key=?', (key,)).fetchone()
            if old and old['value'] != value:
                self._block(db, old['key'], old['value'], old['source_message_id'])
            record = {
                'id': old['id'] if old else str(uuid4()),
                'key': key,
                'value': value,
                'source_message_id': source_message_id,
                'created_at': old['created_at'] if old else now(),
                'updated_at': now(),
            }
            db.execute(
                'INSERT INTO memories VALUES(:id,:key,:value,:source_message_id,:created_at,:updated_at) ON CONFLICT(key) DO UPDATE SET value=excluded.value,source_message_id=excluded.source_message_id,updated_at=excluded.updated_at',
                record,
            )
            db.execute(
                'INSERT INTO memory_events VALUES(?,?,?,?,?,?,?)',
                (str(uuid4()), key, value, source_message_id, evidence, 'save', now()),
            )
            return record

    def recall_history(self, query, current_conversation_id, limit=6):
        terms = re.findall(r'[a-zA-Z0-9]{2,}|[\u4e00-\u9fff]{2,}', query)
        terms = {
            part
            for term in terms
            for part in ([term] if term.isascii() else [term[i : i + 2] for i in range(len(term) - 1)])
        }
        generic = {'记得', '上次', '聊天', '什么', '我们', '那个', '之前', '昨天', '你还', '知道'}
        terms -= generic
        with self.connect() as db:
            blocks = list(db.execute('SELECT * FROM memory_blocks'))
            sql = "SELECT m.*,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.conversation_id<>? AND m.status='complete' AND m.id NOT IN (SELECT message_id FROM forgotten_messages)"
            parameters = [current_conversation_id]
            if terms and not re.search(r'上个聊天|另一个聊天|上次聊|昨天聊', query):
                bounded_terms = sorted(terms, key=lambda term: (-len(term), term))[:20]
                sql += ' AND (' + ' OR '.join('instr(lower(m.content),lower(?))>0' for _ in bounded_terms) + ')'
                parameters.extend(bounded_terms)
            sql += ' ORDER BY m.seq DESC LIMIT 200'
            rows = list(db.execute(sql, parameters))
        ranked = []
        for row in rows:
            if any(row['seq'] <= b['through_seq'] and b['value'] in row['content'] for b in blocks):
                continue
            score = sum(term.casefold() in row['content'].casefold() for term in terms)
            if score or not terms or re.search(r'上个聊天|另一个聊天|上次聊|昨天聊', query):
                ranked.append((score, row['seq'], row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                'message_id': row['id'],
                'conversation_id': row['conversation_id'],
                'title': row['title'],
                'role': row['role'],
                'time': row['created_at'],
                'text': row['content'][:1800],
            }
            for _, _, row in ranked[:limit]
        ]

    def update_summary(self, conversation_id):
        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT id,content,seq FROM messages WHERE conversation_id=? AND role='user' AND status='complete' AND id NOT IN (SELECT message_id FROM forgotten_messages) ORDER BY seq DESC LIMIT 12",
                    (conversation_id,),
                )
            )
            blocks = list(db.execute('SELECT * FROM memory_blocks'))
            rows = [
                r for r in rows if not any(r['seq'] <= b['through_seq'] and b['value'] in r['content'] for b in blocks)
            ]
            summary = '\n'.join(r['content'][:250] for r in reversed(rows))
            db.execute(
                'INSERT INTO conversation_summaries VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET summary=excluded.summary,source_ids=excluded.source_ids,updated_at=excluded.updated_at',
                (conversation_id, summary, json.dumps([r['id'] for r in rows]), now()),
            )
