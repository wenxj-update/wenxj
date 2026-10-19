"""读取指令模板 xlsm 的结构与内容,用于填充真实模板。

输出所有 sheet 名,以及每 sheet 的表头与前几行数据,
帮助理解模板的字段布局。
"""
import sys
from pathlib import Path

import openpyxl

XLSM = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\指令模板_20260918.xlsm"


def main() -> int:
    p = Path(XLSM)
    if not p.is_file():
        print(f"[ERR] not found: {p}")
        return 1

    wb = openpyxl.load_workbook(p, data_only=True, keep_vba=False)
    print(f"# sheets: {len(wb.sheetnames)}")
    for name in wb.sheetnames:
        ws = wb[name]
        print(f"\n=== sheet: {name}  (rows={ws.max_row}, cols={ws.max_column}) ===")
        # 表头(前 2 行)
        for r in range(1, min(ws.max_row, 6) + 1):
            row_vals = []
            for c in range(1, min(ws.max_column, 20) + 1):
                v = ws.cell(row=r, column=c).value
                if v is None:
                    v = ""
                row_vals.append(str(v))
            print(f"  r{r}: {row_vals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
