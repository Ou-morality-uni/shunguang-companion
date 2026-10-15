"""Ordered, transactional upgrades from the pre-versioned database (version 0)."""

SCHEMA_VERSION = 2


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
