"""
Clash Fake-IP + TUN 模式下，akshare 的 requests.Session 会自动读取
macOS 系统代理（urllib.request.getproxies），导致国内数据源请求被代理拦截失败。

此模块在 import 时 monkey-patch requests.Session.__init__，
强制每个新 Session 关闭 trust_env 并清空代理，让 akshare 直连国内数据源。
LLM（langchain/openai SDK）使用 httpx，不受影响。
"""

import requests as _requests

_orig_session_init = _requests.Session.__init__


def _patched_session_init(self, *args, **kwargs):
    _orig_session_init(self, *args, **kwargs)
    self.trust_env = False   # 不读系统代理环境变量
    self.proxies = {}        # 清空代理配置


_requests.Session.__init__ = _patched_session_init
