"""Language-neutral FTS candidates, followed by the existing exact substring filter."""


def tokens(text):
    text = str(text or '').casefold()
    return ' '.join(
        sorted(
            {'u' + char.encode('utf-8').hex() for char in text}
            | {'b' + text[i : i + 2].encode('utf-8').hex() for i in range(len(text) - 1)}
        )
    )


def match_terms(terms):
    groups = []
    for term in terms:
        term = term.casefold()
        pieces = (
            ['u' + term.encode('utf-8').hex()]
            if len(term) == 1
            else ['b' + term[i : i + 2].encode('utf-8').hex() for i in range(min(len(term) - 1, 64))]
        )
        if pieces:
            groups.append('(' + ' AND '.join('"' + value + '"' for value in pieces) + ')')
    return ' OR '.join(groups)


def migrate(db):
    for source, target, field, complete in (
        ('messages', 'message_search', 'content', True),
        ('conversation_episodes', 'episode_search', 'summary', False),
    ):
        db.execute(f'CREATE VIRTUAL TABLE IF NOT EXISTS {target} USING fts5(tokens)')
        condition = "WHERE status='complete'" if complete else ''
        db.execute(f'DELETE FROM {target}')
        db.execute(f'INSERT INTO {target}(rowid,tokens) SELECT rowid,recall_tokens({field}) FROM {source} {condition}')
        new_condition = "WHERE new.status='complete'" if complete else ''
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS {target}_insert AFTER INSERT ON {source} BEGIN
            INSERT INTO {target}(rowid,tokens) SELECT new.rowid,recall_tokens(new.{field}) {new_condition}; END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS {target}_delete AFTER DELETE ON {source} BEGIN
            DELETE FROM {target} WHERE rowid=old.rowid; END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS {target}_update AFTER UPDATE OF {field}{',status' if complete else ''} ON {source} BEGIN
            DELETE FROM {target} WHERE rowid=old.rowid;
            INSERT INTO {target}(rowid,tokens) SELECT new.rowid,recall_tokens(new.{field}) {new_condition}; END""")
