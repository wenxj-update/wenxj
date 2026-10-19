"""算法库加载层:ctypes 通用 dll 加载 + 签名注册表 + 可见性/数传算法抽象。

扩展点:
- 真实 .dll 函数签名在 signature.py 的 SignatureRegistry 注册(扩展点2)
- 真实调用细节在 visibility.py 的 CtVisibilityAlgorithm 补全(扩展点3)
"""
