import sys
import types


class _DummyHttpxClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        raise RuntimeError("stub client")


sys.modules.setdefault("httpx", types.SimpleNamespace(Client=_DummyHttpxClient))

sys.modules.setdefault("markdownify", types.SimpleNamespace(markdownify=lambda html: html))
