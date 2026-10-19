"""MVP 用桩:复用 algorithm.visibility.StubVisibilityAlgorithm。

真实 .dll 不可用时,主链路用此桩跑通。
另见 gen_mock_dll.c(可选,编译小 dll 验证 DllLoader 加载链路)。
"""
from rwgh.algorithm.visibility import StubVisibilityAlgorithm  # noqa: F401
