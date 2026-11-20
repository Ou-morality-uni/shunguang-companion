"""Cross-process lease shared by the foreground service and dependency installer."""

import os


def environment_lock(root, name='environment'):
    directory = root / 'data/install'
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / (name + '.lock')).open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError(
            'Project is already running or installing; close its original window before updating.'
        ) from None
    return stream  # The OS releases the lease on close or process termination.
