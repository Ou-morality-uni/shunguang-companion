"""Local dependency readiness without loading models or calling providers."""

from . import config, runtime
from .office_runtime import find_office


def dependencies():
    state = {
        'storage': 'unavailable',
        'model': 'unconfigured',
        'rag': 'disabled' if not config.local_knowledge_enabled() else 'not_ready',
        'office': 'available_on_demand' if find_office() else 'not_installed',
    }
    try:
        if runtime.store.path.is_file():
            with runtime.store.connect() as db:
                db.execute('SELECT id FROM conversations LIMIT 1').fetchone()
            state['storage'] = 'ready'
    except Exception:
        state['storage'] = 'unavailable'
    try:
        value = config.load_config()
        state['model'] = 'ready' if config.public_config(value)['configured'] else 'unconfigured'
    except Exception:
        state['model'] = 'credentials_unreadable'
    if config.local_knowledge_enabled():
        from . import rag

        try:
            state['rag'] = 'ready' if rag.status().get('ready') else 'not_ready'
        except Exception:
            state['rag'] = 'unavailable'
    from .edition import dependency_status

    state.update(dependency_status())
    return state
