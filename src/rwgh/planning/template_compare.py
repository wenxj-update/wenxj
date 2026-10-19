"""模板比对:指令序列 vs 期望模板,输出时序+码字差异。

比对策略:
- 按 time_tag 最近邻对齐(在容差内)
- 码字比对优先级: codeword(bytes) > name+headers > code(int)
  - 真实模板:codeword 非空时按 bytes 精确比对;数据块(codeword 空)按 name 比对
  - stub 链路:codeword 均空,回退到 code(int) 比对
- 输出 matches + discrepancies(时序/码字/缺失/多余)
"""
from __future__ import annotations

import logging
from typing import Optional

from ..models.command import Command, CommandSequence, CommandTemplate
from ..models.comparison import ComparisonResult, Discrepancy

_log = logging.getLogger("rwgh.planning.template_compare")


def _codeword_match(exp: Command, act: Command) -> bool:
    """码字比对:真实模板用 codeword+name,stub 用 code(int)。"""
    # 双方都有 codeword:按 bytes 精确比对
    if exp.codeword and act.codeword:
        if exp.codeword != act.codeword:
            return False
        # codeword 匹配后,name 也需一致(若有)
        if exp.name and act.name and exp.name != act.name:
            return False
        return True
    # 期望是数据块(codeword 空,如"记录任务包"):按 name+headers 比对
    if exp.codeword == b"" and exp.name:
        if not act.name:
            return False
        if exp.name != act.name:
            return False
        return True
    # 双方都无 codeword 且无 name:回退到 code(int)
    return act.code == exp.code


class TemplateComparator:
    """指令序列与模板比对。"""

    def __init__(self, templates: dict[str, CommandTemplate] | None = None) -> None:
        self._templates: dict[str, CommandTemplate] = dict(templates or {})

    def register(self, template: CommandTemplate) -> None:
        self._templates[template.name] = template

    def get(self, name: str) -> Optional[CommandTemplate]:
        return self._templates.get(name)

    def compare(self, seq: CommandSequence,
                template_name: str) -> ComparisonResult:
        tmpl = self._templates.get(template_name)
        if tmpl is None:
            return ComparisonResult(
                template_name=template_name,
                target_id=seq.target_id,
                passed=False,
                discrepancies=(Discrepancy(
                    kind="missing", detail=f"template not found: {template_name}"),),
            )

        expected = list(tmpl.expected)
        actual = list(seq.commands)
        matches: list[Command] = []
        discrepancies: list[Discrepancy] = []

        # 期望逐条在 actual 中找最近邻匹配
        used = [False] * len(actual)
        for i, exp in enumerate(expected):
            best_j, best_dt = -1, float("inf")
            for j, act in enumerate(actual):
                if used[j]:
                    continue
                dt = abs(act.time_tag - exp.time_tag)
                if dt < best_dt:
                    best_dt, best_j = dt, j
            if best_j < 0:
                discrepancies.append(Discrepancy(
                    kind="missing", index=i,
                    detail=f"no actual command for expected #{i}",
                    expected=exp))
                continue
            act = actual[best_j]
            # 时序差异
            if best_dt > tmpl.time_tolerance:
                discrepancies.append(Discrepancy(
                    kind="time", index=i,
                    detail=f"time_tag drift {best_dt:.3f}s > tol {tmpl.time_tolerance}s",
                    expected=exp.time_tag, actual=act.time_tag))
            # 码字差异
            elif tmpl.code_exact and not _codeword_match(exp, act):
                discrepancies.append(Discrepancy(
                    kind="code", index=i,
                    detail=f"codeword/name mismatch (exp={exp.name} cw={exp.codeword.hex()}, "
                           f"act={act.name} cw={act.codeword.hex()})",
                    expected=exp, actual=act))
            else:
                matches.append(act)
            used[best_j] = True

        # 多余指令
        for j, act in enumerate(actual):
            if not used[j]:
                discrepancies.append(Discrepancy(
                    kind="extra", index=j,
                    detail="unexpected extra command",
                    actual=act))

        passed = len(discrepancies) == 0
        _log.info("compare target=%s template=%s: %d match, %d discrepancy, passed=%s",
                  seq.target_id, template_name, len(matches),
                  len(discrepancies), passed)
        return ComparisonResult(
            template_name=template_name,
            target_id=seq.target_id,
            matches=tuple(matches),
            discrepancies=tuple(discrepancies),
            passed=passed,
        )
