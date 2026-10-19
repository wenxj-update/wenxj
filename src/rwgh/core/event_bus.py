"""进程内事件总线:线程安全 pub/sub,解耦各环节。"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[Any], None]
Unsubscribe = Callable[[], None]


class Topics:
    """约定的事件主题常量。"""
    RAW_FRAME = "raw_frame"                     # 原始二进制帧(TCP 接收/Framer 产出)
    STK_MESSAGE = "stk_message"                 # STK 报文解析结果
    PARSED_PACKET = "parsed_packet"             # 通用数据包解析结果(子主题按格式名细分)
    TARGET_SET = "target_set"                   # 场景真实地面目标列表(list[TargetPoint])
    VISIBILITY_RESULT = "visibility_result"     # 可见性计算结果
    VISIBILITY_REPORT_FRAME = "visibility_report_frame"  # 可见性报文帧(回送)
    COMMAND_SEQUENCE = "command_sequence"       # 指令序列
    COMPARISON_RESULT = "comparison_result"     # 模板比对结果
    LOG = "log"                                 # 日志事件(可选,供 UI 订阅)


class EventBus:
    """线程安全的进程内事件总线。

    publish 在持有锁的情况下复制订阅者快照后释放锁再调用,
    避免 handler 内再次订阅/退订造成死锁。
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: Handler) -> Unsubscribe:
        with self._lock:
            self._subs[topic].append(handler)

        def _unsubscribe() -> None:
            with self._lock:
                lst = self._subs.get(topic, [])
                if handler in lst:
                    lst.remove(handler)

        return _unsubscribe

    def publish(self, topic: str, payload: Any = None) -> None:
        # 快照订阅者,避免回调中修改列表
        with self._lock:
            handlers = list(self._subs.get(topic, ()))
        for h in handlers:
            try:
                h(payload)
            except Exception:  # noqa: BLE001 - 单个 handler 异常不影响其他
                # 日志记录但不中断总线
                import logging
                logging.getLogger(__name__).exception(
                    "event handler error topic=%s", topic
                )

    def unsubscribe_all(self) -> None:
        with self._lock:
            self._subs.clear()
