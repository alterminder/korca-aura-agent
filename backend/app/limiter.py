import sys

from slowapi import Limiter
from slowapi.util import get_ipaddr

from app.config import settings

# Use Redis as the process-safe shared storage backend, fallback to in-memory for tests
is_testing = "pytest" in sys.modules
storage_uri = (
    "memory://" if is_testing else (settings.redis_url if settings.redis_url else "memory://")
)

limiter = Limiter(
    key_func=get_ipaddr,  # honours X-Forwarded-For — correct behind k8s ingress / Docker proxy
    storage_uri=storage_uri,
    strategy="moving-window",
    enabled=not is_testing,
)
