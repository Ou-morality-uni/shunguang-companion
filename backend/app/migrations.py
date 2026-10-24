"""Ordered, transactional upgrades from the pre-versioned database (version 0)."""

SCHEMA_VERSION = 9


def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError('数据库版本高于当前程序，请使用较新版本。')
    db.execute('BEGIN IMMEDIATE')
    if version < 1:
        for statement in LEGACY_SCHEMA.split(';'):
            if statement.strip():
                db.execute(statement)
        columns = {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
        if 'metadata' not in columns:
            db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        db.execute('PRAGMA user_version=1')
    if version < 2:
        db.execute('ALTER TABLE messages RENAME TO messages_legacy')
        db.execute("""CREATE TABLE messages (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")
        db.execute("""INSERT INTO messages(id,conversation_id,role,content,status,created_at,metadata)
            SELECT id,conversation_id,role,content,status,created_at,metadata
            FROM messages_legacy ORDER BY rowid""")
        db.execute('DROP TABLE messages_legacy')
        db.execute('CREATE INDEX messages_conversation ON messages(conversation_id,seq)')
        db.execute('PRAGMA user_version=2')
    if version < 3:
        db.execute('CREATE TABLE forgotten_messages (message_id TEXT PRIMARY KEY)')
        db.execute("""CREATE TABLE memory_events (
            id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
            source_message_id TEXT, evidence TEXT NOT NULL, action TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE memory_blocks (
            key TEXT NOT NULL, value TEXT NOT NULL, through_seq INTEGER NOT NULL,
            PRIMARY KEY(key,value)
        )""")
        db.execute("""CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY, summary TEXT NOT NULL,
            source_ids TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")
        db.execute('PRAGMA user_version=3')
    if version < 4:
        db.execute("""CREATE TABLE workspaces (
            id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, identity TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE file_tasks (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL, steps TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
        )""")
        db.execute('CREATE INDEX file_tasks_recent ON file_tasks(created_at)')
        db.execute('PRAGMA user_version=4')
    if version < 5:
        db.execute("ALTER TABLE file_tasks ADD COLUMN origin TEXT NOT NULL DEFAULT 'workbench'")
        db.execute("""CREATE TABLE work_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES file_tasks(id)
        )""")
        db.execute('CREATE INDEX work_events_task ON work_events(task_id,seq)')
        db.execute('PRAGMA user_version=5')
    if version < 6:
        db.execute(
            'ALTER TABLE file_tasks ADD COLUMN conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL'
        )
        db.execute("ALTER TABLE file_tasks ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
        db.execute('CREATE INDEX file_tasks_conversation ON file_tasks(conversation_id,created_at)')
        db.execute('CREATE TABLE work_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('PRAGMA user_version=6')
    if version < 7:
        db.execute("""CREATE TABLE conversation_models (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL, model TEXT NOT NULL, effort TEXT NOT NULL
        )""")
        db.execute('PRAGMA user_version=7')
    if version < 8:
        db.execute("""CREATE TABLE memory_jobs (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            through_seq INTEGER NOT NULL DEFAULT 0, requested_seq INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', model_choice TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("""CREATE TABLE conversation_episodes (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            start_seq INTEGER NOT NULL, end_seq INTEGER NOT NULL, summary TEXT NOT NULL,
            source_ids TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(conversation_id,start_seq,end_seq)
        )""")
        db.execute('PRAGMA user_version=8')
    if version < 9:
        db.execute("""CREATE TABLE annotations (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
            draft_scope TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            submitted_message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute('CREATE INDEX annotations_scope ON annotations(conversation_id,draft_scope,status)')
        db.execute('PRAGMA user_version=9')


LEGACY_SCHEMA = """
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
"""
