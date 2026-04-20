"""简单的内存级 TTL 缓存装饰器。

用于降低 AkShare 接口调用频率——同一参数在 TTL 内只打一次远程请求。
"""
import time
from functools import wraps
from typing import Any, Callable, Dict, Tuple


def ttl_cache(seconds: int = 600):
    """装饰器：对函数结果做 TTL 缓存。key = (args, sorted kwargs)。"""
    def decorator(func: Callable) -> Callable:
        store: Dict[Tuple, Tuple[float, Any]] = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            hit = store.get(key)
            if hit and now - hit[0] < seconds:
                return hit[1]
            value = func(*args, **kwargs)
            store[key] = (now, value)
            return value

        wrapper.cache_clear = store.clear  # type: ignore
        return wrapper

    return decorator
