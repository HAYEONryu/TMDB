import socket
import time
import urllib.error
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_http(url, process, *, context=None):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError('Verification server exited during startup')
        try:
            with urllib.request.urlopen(url, timeout=1, context=context) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(.1)
    raise AssertionError('Verification server startup timeout')
