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

    def create_file_task(self, workspace_id, title, steps, status, origin='workbench', conversation_id=None):
        task_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                'INSERT INTO file_tasks(id,workspace_id,title,status,steps,error,created_at,updated_at,origin,conversation_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (
                    task_id,
                    workspace_id,
                    title,
                    status,
                    json.dumps(steps, ensure_ascii=False),
                    '',
                    now(),
                    now(),
                    origin,
                    conversation_id,
                ),
            )
        return self.get_file_task(task_id)

    def get_file_task(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM file_tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                return None
            record = dict(row)
            record['steps'] = json.loads(record['steps'])
            record['context'] = json.loads(record['context'])
            record['events'] = [
                dict(event)
                for event in db.execute('SELECT * FROM work_events WHERE task_id=? ORDER BY seq', (task_id,))
            ]
            return record

    def list_file_tasks(self, limit=50, conversation_id=None):
        with self.connect() as db:
            query = 'SELECT * FROM file_tasks'
            params = []
            if conversation_id is not None:
                query += ' WHERE conversation_id=?'
                params.append(conversation_id)
            rows = db.execute(query + ' ORDER BY created_at DESC LIMIT ?', (*params, limit))
            records = [
                {**dict(row), 'steps': json.loads(row['steps']), 'context': json.loads(row['context'])} for row in rows
            ]
            for record in records:
                record['events'] = [
                    dict(event)
                    for event in db.execute('SELECT * FROM work_events WHERE task_id=? ORDER BY seq', (record['id'],))
                ]
            return records

    def save_file_task(self, record):
        record['updated_at'] = now()
        with self.connect() as db:
            db.execute(
                'UPDATE file_tasks SET status=?,steps=?,error=?,updated_at=?,context=? WHERE id=?',
                (
                    record['status'],
                    json.dumps(record['steps'], ensure_ascii=False),
                    record['error'],
                    record['updated_at'],
                    json.dumps(record.get('context', {}), ensure_ascii=False),
                    record['id'],
                ),
            )

    def output_workspace(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM work_settings WHERE key='output_workspace'").fetchone()
        return self.get_workspace(row['value']) if row else None

    def set_output_workspace(self, workspace_id):
        with self.connect() as db:
            db.execute(
                "INSERT INTO work_settings VALUES ('output_workspace',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (workspace_id,),
            )

    def interrupt_file_tasks(self):
        with self.connect() as db:
            db.execute(
                "UPDATE file_tasks SET status='interrupted',error=?,updated_at=? WHERE status IN ('queued','running','restoring')",
                ('服务已重启。请检查操作记录，按需恢复；不会自动重放文件操作。', now()),
            )

    def add_work_event(self, task_id, kind, text):
        with self.connect() as db:
            db.execute(
                'INSERT INTO work_events(task_id,kind,text,created_at) VALUES (?,?,?,?)', (task_id, kind, text, now())
            )

    def work_events(self, after=None):
        with self.connect() as db:
            latest = db.execute('SELECT COALESCE(MAX(seq),0) FROM work_events').fetchone()[0]
            rows = (
                []
                if after is None
                else [
                    dict(row)
                    for row in db.execute('SELECT * FROM work_events WHERE seq>? ORDER BY seq LIMIT 100', (after,))
                ]
            )
            return {'cursor': rows[-1]['seq'] if rows else latest, 'events': rows}

    def create_conversation(self):
        record = {'id': str(uuid4()), 'title': '新的对话', 'created_at': now(), 'updated_at': now()}
        with self.connect() as db:
            db.execute('INSERT INTO conversations VALUES (:id,:title,:created_at,:updated_at)', record)
        return record

    def begin_turn(self, conversation_id: str | None, content: str, metadata=None):
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
                'INSERT INTO messages(id,conversation_id,role,content,status,created_at,metadata) VALUES (:id,:conversation_id,:role,:content,:status,:created_at,:metadata)',
                {**record, 'metadata': json.dumps(metadata or {}, ensure_ascii=False)},
            )
            for annotation in (metadata or {}).get('annotations', []):
                changed = db.execute(
                    "UPDATE annotations SET status='submitted',conversation_id=?,submitted_message_id=?,updated_at=? WHERE id=? AND status='draft' AND updated_at=?",
                    (conversation_id, record['id'], now(), annotation['id'], annotation['updated_at']),
                ).rowcount
                if changed != 1:
                    from .filework import WorkError

                    raise WorkError('批注草稿刚刚变化，请刷新后重新发送。')
            db.execute(
                "UPDATE conversations SET title=CASE WHEN title='新的对话' THEN ? ELSE title END, updated_at=? WHERE id=?",
                (content[:24], now(), conversation_id),
            )
            return {**record, **(metadata or {})}

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

    def conversation_model(self, conversation_id):
        with self.connect() as db:
            row = db.execute(
                'SELECT profile_id,model,effort FROM conversation_models WHERE conversation_id=?', (conversation_id,)
            ).fetchone()
            return dict(row) if row else None

    def set_conversation_model(self, conversation_id, choice):
        with self.connect() as db:
            db.execute(
                """INSERT INTO conversation_models VALUES(?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET profile_id=excluded.profile_id,model=excluded.model,effort=excluded.effort""",
                (conversation_id, choice['profile_id'], choice['model'], choice['effort']),
            )

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
                        'attachments': metadata.get('attachments', []),
                        'annotations': metadata.get('annotations', []),
                        'history_sources': [
                            {**source, 'text': source['text'][:1800]}
                            for item in metadata.get('history_sources', [])
                            if isinstance(item, dict)
                            for source in [self._history_source(db, item.get('message_id', ''))]
                            if source
                        ],
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

    def user_profile(self):
        from .memory import canonical_key

        facts = {}
        for item in self.list_memories():
            facts.setdefault(canonical_key(item['key'], item['value']), item['value'])
        age = facts.get('年龄', '')
        return {
            'nickname': facts.get('对用户的称呼', '小师妹'),
            'city': facts.get('居住地', ''),
            'age': int(age) if age.isdecimal() and 1 <= int(age) <= 120 else None,
        }

    def update_user_profile(self, patch):
        from .memory import canonical_key

        fields = {'nickname': '对用户的称呼', 'city': '居住地', 'age': '年龄'}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for field, value in patch.items():
                key = fields[field]
                text = '' if value is None else str(value)
                old = [
                    dict(row)
                    for row in db.execute('SELECT * FROM memories')
                    if canonical_key(row['key'], row['value']) == key
                ]
                for item in old:
                    if item['value'] != text:
                        self._block(db, item['key'], item['value'], item['source_message_id'])
                    db.execute('DELETE FROM memories WHERE id=?', (item['id'],))
                if text:
                    record = {
                        'id': old[0]['id'] if old else str(uuid4()),
                        'key': key,
                        'value': text,
                        'source_message_id': None,
                        'created_at': old[0]['created_at'] if old else now(),
                        'updated_at': now(),
                    }
                    db.execute(
                        'INSERT INTO memories VALUES(:id,:key,:value,:source_message_id,:created_at,:updated_at)',
                        record,
                    )
                    db.execute(
                        'INSERT INTO memory_events VALUES(?,?,?,?,?,?,?)',
                        (str(uuid4()), key, text, None, '用户在个人资料中填写', 'manual', now()),
                    )
        return self.user_profile()

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
        affected = list(
            db.execute(
                """SELECT e.conversation_id,MIN(e.start_seq) AS start_seq FROM conversation_episodes e
            WHERE EXISTS(SELECT 1 FROM json_each(e.source_ids) ids JOIN messages m ON m.id=ids.value
                WHERE m.id IN (SELECT message_id FROM forgotten_messages)
                OR (m.seq<=? AND instr(m.content,?)>0)) GROUP BY e.conversation_id""",
                (boundary, value),
            )
        )
        for episode in affected:
            db.execute(
                'DELETE FROM conversation_episodes WHERE conversation_id=? AND start_seq>=?',
                (episode['conversation_id'], episode['start_seq']),
            )
            db.execute(
                "UPDATE memory_jobs SET through_seq=MIN(through_seq,?),status=CASE WHEN status='running' THEN status ELSE 'queued' END WHERE conversation_id=?",
                (episode['start_seq'] - 1, episode['conversation_id']),
            )

    def save_fact(self, key, value, evidence, source_message_id):
        from .memory import SENSITIVE, canonical_key, temporary_residence

        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            source = db.execute(
                "SELECT * FROM messages WHERE id=? AND role='user' AND status='complete'", (source_message_id,)
            ).fetchone()
            if (
                not source
                or SENSITIVE.search(source['content'])
                or evidence not in source['content']
                or value not in evidence
                or db.execute('SELECT 1 FROM forgotten_messages WHERE message_id=?', (source_message_id,)).fetchone()
            ):
                raise ValueError('没有可核对的用户原话')
            if canonical_key(key, value) == '居住地' and temporary_residence(source['content']):
                raise ValueError('临时出行不能覆盖常住地')
            context = db.execute(
                "SELECT content FROM messages WHERE conversation_id=? AND role='user' AND seq<=? ORDER BY seq DESC LIMIT 6",
                (source['conversation_id'], source['seq']),
            )
            if any(re.search(r'我们.*扮演|我扮演|我的角色|设定我是', item['content']) for item in context):
                raise ValueError('角色扮演不能作为现实用户事实')
            if (
                key == '年龄'
                and (not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 120)
                or key == '对用户的称呼'
                and (not value.strip() or len(value) > 40)
                or key == '居住地'
                and len(value) > 80
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError('用户资料格式不正确')
            if db.execute(
                'SELECT 1 FROM memory_blocks WHERE value=? AND through_seq>=?', (value, source['seq'])
            ).fetchone():
                raise ValueError('此来源已被用户要求忘记')
            old = db.execute('SELECT * FROM memories WHERE key=?', (key,)).fetchone()
            if old and old['value'] != value:
                previous = db.execute('SELECT seq FROM messages WHERE id=?', (old['source_message_id'],)).fetchone()
                if (previous and previous['seq'] >= source['seq']) or (
                    not previous and old['updated_at'] > source['created_at']
                ):
                    raise ValueError('不能用较旧的消息覆盖更新的用户资料')
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

    def recall_history(self, query, current_conversation_id, limit=6, automatic=False):
        from .memory import SENSITIVE

        terms = re.findall(r'[a-zA-Z0-9]{2,}|[\u4e00-\u9fff]{2,}', query)
        terms = {
            part
            for term in terms
            for part in ([term] if term.isascii() else [term[i : i + 2] for i in range(len(term) - 1)])
        }
        generic = {'记得', '上次', '聊天', '什么', '我们', '那个', '之前', '昨天', '你还', '知道'}
        terms -= generic
        if automatic:
            terms -= {
                '帮我',
                '一下',
                '你好',
                '谢谢',
                '可以',
                '今天',
                '继续',
                '接着',
                '请问',
                '看看',
                '现在',
                '这个',
                '一下',
                '早上',
                '晚上',
            }
            if not terms and not re.search(r'上个聊天|另一个聊天|上次聊|昨天聊', query):
                return []
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
            if terms:
                bounded = sorted(terms, key=lambda term: (-len(term), term))[:20]
                episode_sql = (
                    """SELECT m.*,c.title,e.summary AS episode_summary FROM conversation_episodes e
                    JOIN json_each(e.source_ids) ids JOIN messages m ON m.id=ids.value JOIN conversations c ON c.id=m.conversation_id
                    WHERE e.conversation_id<>? AND m.status='complete'
                    AND NOT EXISTS(SELECT 1 FROM json_each(e.source_ids) source LEFT JOIN messages original ON original.id=source.value
                        WHERE original.id IS NULL OR original.id IN (SELECT message_id FROM forgotten_messages)
                        OR EXISTS(SELECT 1 FROM memory_blocks b WHERE original.seq<=b.through_seq AND instr(original.content,b.value)>0))
                    AND ("""
                    + ' OR '.join('instr(lower(e.summary),lower(?))>0' for _ in bounded)
                    + ') ORDER BY e.end_seq DESC LIMIT 200'
                )
                rows += list(db.execute(episode_sql, [current_conversation_id, *bounded]))
        ranked = []
        for row in rows:
            if SENSITIVE.search(row['content']):
                continue
            if any(row['seq'] <= b['through_seq'] and b['value'] in row['content'] for b in blocks):
                continue
            score = sum(term.casefold() in row['content'].casefold() for term in terms)
            if 'episode_summary' in row.keys():
                score += sum(term.casefold() in row['episode_summary'].casefold() for term in terms)
            if score or not terms or re.search(r'上个聊天|另一个聊天|上次聊|昨天聊', query):
                ranked.append((score, row['seq'], row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        unique = {}
        for score, seq, row in ranked:
            unique.setdefault(row['id'], (score, seq, row))
        return [
            {
                'message_id': row['id'],
                'conversation_id': row['conversation_id'],
                'title': row['title'],
                'role': row['role'],
                'time': row['created_at'],
                'text': row['content'][:1800],
                **({'episode_summary': row['episode_summary']} if 'episode_summary' in row.keys() else {}),
            }
            for _, _, row in list(unique.values())[:limit]
        ]

    @staticmethod
    def _history_source(db, message_id):
        from .memory import SENSITIVE

        row = db.execute(
            """SELECT m.*,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id
            WHERE m.id=? AND m.status='complete' AND m.id NOT IN (SELECT message_id FROM forgotten_messages)
            AND NOT EXISTS(SELECT 1 FROM memory_blocks b WHERE m.seq<=b.through_seq AND instr(m.content,b.value)>0)""",
            (message_id,),
        ).fetchone()
        if not row or SENSITIVE.search(row['content']):
            return None
        episode = db.execute(
            """SELECT e.summary FROM conversation_episodes e JOIN json_each(e.source_ids) ids
            WHERE ids.value=? AND NOT EXISTS(SELECT 1 FROM json_each(e.source_ids) source LEFT JOIN messages m ON m.id=source.value
                WHERE m.id IS NULL OR m.id IN (SELECT message_id FROM forgotten_messages)
                OR EXISTS(SELECT 1 FROM memory_blocks b WHERE m.seq<=b.through_seq AND instr(m.content,b.value)>0))
            ORDER BY e.end_seq DESC LIMIT 1""",
            (message_id,),
        ).fetchone()
        return {
            'message_id': row['id'],
            'conversation_id': row['conversation_id'],
            'title': row['title'],
            'role': row['role'],
            'time': row['created_at'],
            'text': row['content'],
            **({'episode_summary': episode['summary']} if episode else {}),
        }

    def history_source(self, message_id):
        with self.connect() as db:
            return self._history_source(db, message_id)

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

    def queue_memory(self, conversation_id, choice=None):
        from .model_choices import default_choice

        explicit_choice = choice is not None
        choice = choice or self.conversation_model(conversation_id) or default_choice()
        with self.connect() as db:
            target = db.execute(
                "SELECT MAX(seq) FROM messages WHERE conversation_id=? AND role='user' AND status='complete'",
                (conversation_id,),
            ).fetchone()[0]
            if target is None:
                return
            if not explicit_choice:
                previous = db.execute(
                    'SELECT model_choice FROM memory_jobs WHERE conversation_id=?', (conversation_id,)
                ).fetchone()
                if previous:
                    choice = json.loads(previous['model_choice'])
            db.execute(
                """INSERT INTO memory_jobs(conversation_id,requested_seq,model_choice) VALUES(?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET requested_seq=MAX(requested_seq,excluded.requested_seq),
                model_choice=excluded.model_choice, error='',
                status=CASE WHEN status='running' THEN status WHEN through_seq<excluded.requested_seq THEN 'queued' ELSE status END""",
                (conversation_id, target, json.dumps(choice)),
            )

    def queue_memory_backfill(self, recover=False):
        if recover:
            with self.connect() as db:
                db.execute("UPDATE memory_jobs SET status='queued' WHERE status='running'")
        for conversation in self.list_conversations():
            self.queue_memory(conversation['id'])

    def next_memory_batch(self):
        from .memory import SENSITIVE, forget_request

        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute(
                "SELECT * FROM memory_jobs WHERE status='queued' AND requested_seq>through_seq ORDER BY requested_seq LIMIT 1"
            ).fetchone()
            if not job:
                return None
            rows = list(
                db.execute(
                    """SELECT m.* FROM messages m WHERE conversation_id=? AND role='user' AND status='complete'
                AND seq>? AND seq<=? AND id NOT IN (SELECT message_id FROM forgotten_messages)
                AND NOT EXISTS (SELECT 1 FROM memory_blocks b WHERE m.seq<=b.through_seq AND instr(m.content,b.value)>0)
                ORDER BY seq LIMIT 12""",
                    (job['conversation_id'], job['through_seq'], job['requested_seq']),
                )
            )
            messages, size, through = [], 0, job['through_seq']
            for row in rows:
                if messages and size + len(row['content']) > 24000:
                    break
                through = row['seq']
                if SENSITIVE.search(row['content']) or forget_request(row['content']):
                    continue
                messages.append(dict(row))
                size += len(row['content'])
            if not messages:
                through = through if rows else job['requested_seq']
                db.execute(
                    "UPDATE memory_jobs SET through_seq=?,status=CASE WHEN requested_seq>? THEN 'queued' ELSE 'idle' END WHERE conversation_id=?",
                    (through, through, job['conversation_id']),
                )
            else:
                db.execute("UPDATE memory_jobs SET status='running' WHERE conversation_id=?", (job['conversation_id'],))
            return {**dict(job), 'messages': messages, 'end_seq': through, 'choice': json.loads(job['model_choice'])}

    def finish_memory_batch(self, job, summary):
        messages = job['messages']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute(
                'SELECT 1 FROM memory_jobs WHERE conversation_id=?', (job['conversation_id'],)
            ).fetchone():
                return
            for message in messages:
                valid = db.execute(
                    """SELECT 1 FROM messages m WHERE id=? AND content=? AND status='complete'
                    AND NOT EXISTS(SELECT 1 FROM forgotten_messages WHERE message_id=m.id)
                    AND NOT EXISTS(SELECT 1 FROM memory_blocks b WHERE m.seq<=b.through_seq AND instr(m.content,b.value)>0)""",
                    (message['id'], message['content']),
                ).fetchone()
                if not valid:
                    db.execute(
                        "UPDATE memory_jobs SET status='queued' WHERE conversation_id=?", (job['conversation_id'],)
                    )
                    return
            db.execute(
                'INSERT OR REPLACE INTO conversation_episodes VALUES(?,?,?,?,?,?)',
                (
                    job['conversation_id'],
                    messages[0]['seq'],
                    messages[-1]['seq'],
                    summary,
                    json.dumps([item['id'] for item in messages]),
                    now(),
                ),
            )
            db.execute(
                "UPDATE memory_jobs SET through_seq=?,status=CASE WHEN requested_seq>? THEN 'queued' ELSE 'idle' END,error='' WHERE conversation_id=?",
                (job['end_seq'], job['end_seq'], job['conversation_id']),
            )

    def memory_job_state(self, conversation_id, status, error=''):
        with self.connect() as db:
            db.execute(
                'UPDATE memory_jobs SET status=?,error=? WHERE conversation_id=?', (status, error, conversation_id)
            )

    def memory_status(self):
        with self.connect() as db:
            counts = {
                row['status']: row['n']
                for row in db.execute('SELECT status,COUNT(*) n FROM memory_jobs GROUP BY status')
            }
            return {
                **{key: counts.get(key, 0) for key in ('queued', 'running', 'failed', 'paused')},
                'summaries': db.execute('SELECT COUNT(*) FROM conversation_episodes').fetchone()[0],
            }
