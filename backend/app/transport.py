"""Use normal OS certificate trust; verification is never disabled."""

import os
import ssl

if os.name == 'nt':
    import truststore

    # Application entry-point behavior recommended for Windows SDK clients.
    truststore.inject_into_ssl()


def ssl_context():
    return ssl.create_default_context()
