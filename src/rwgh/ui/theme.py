"""全局视觉主题:深空科技风(航天测控大屏配色)。

集中维护调色板、字体与 QSS,各视图只引用语义色,不散落硬编码颜色。
配色借鉴航天测控数据可视化大屏:深空蓝黑底 + 青色主调 + 橙/绿/红状态色。
"""
from __future__ import annotations


# ---------- 语义调色板(深空科技风) ----------

class C:
    """配色常量(Hex)。"""

    # 背景层级(由深到浅)
    BG_APP = "#0a0f1c"          # 窗口底色(深空黑蓝)
    BG_PANEL = "#111a2e"        # 卡片/面板
    BG_PANEL_2 = "#16223a"      # 次级面板/悬停
    BG_PANEL_3 = "#1c2a45"      # 三级面板(表头/强调背景)
    BG_TABLE = "#0d1524"        # 表格底
    BG_TABLE_ALT = "#111c30"    # 交替行
    BG_TABLE_SEL = "#1a3354"    # 选中行

    # 边框/分隔
    BORDER = "#2a3d5e"
    BORDER_SOFT = "#1e2c44"
    BORDER_GLOW = "#3a6ea5"     # 发光边框

    # 文字
    FG = "#eaf2ff"
    FG_DIM = "#8a9bbb"
    FG_FAINT = "#5a6b85"

    # 强调(青色主调 - 科技感)
    ACCENT = "#22d3ee"          # 主青
    ACCENT_DEEP = "#0891b2"
    ACCENT_SOFT = "#0e3a4a"
    ACCENT_LIGHT = "#67e8f9"

    # 卫星类型
    GOLD = "#fbbf24"            # 光星 - 金
    GOLD_SOFT = "#3d2f12"
    SILVER = "#cbd5e1"          # SAR - 银
    SILVER_SOFT = "#263042"

    # 状态
    OK = "#34d399"              # 通过/运行 - 翠绿
    OK_SOFT = "#0d3329"
    WARN = "#fbbf24"            # 警告 - 琥珀
    WARN_SOFT = "#3d2f12"
    ERR = "#f87171"             # 失败/错误 - 珊瑚红
    ERR_SOFT = "#3d1f24"
    INFO = "#60a5fa"            # 信息 - 蓝

    # 包类型配色(报文徽章)
    PKT_TIME = "#22d3ee"        # 0x0B01 星时 - 青
    PKT_ELEM = "#34d399"        # 0xA012 根数 - 绿
    PKT_DATA = "#a78bfa"        # 0xA002 轨道 - 紫
    PKT_REPORT = "#fbbf24"      # 0x5B5B 可见性报文 - 橙
    PKT_UNKNOWN = "#7c8aa5"     # 未知 - 灰

    # 设施/目标
    FACILITY = "#fbbf24"
    TARGET = "#60a5fa"


# ---------- 字体 ----------

FONT_UI = '"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif'
FONT_MONO = '"Cascadia Mono","Consolas","Courier New",monospace'


# ---------- 全局 QSS ----------

APP_QSS = f"""
* {{
    font-family: {FONT_UI};
    font-size: 12px;
    outline: none;
}}

QMainWindow, QDialog {{
    background: {C.BG_APP};
}}

QWidget {{
    color: {C.FG};
}}

/* ---------- 顶部标题区(深空科技风) ---------- */
#HeaderBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f1d35, stop:0.5 #0c1729, stop:1 #0a1120);
    border-bottom: 1px solid {C.BORDER_GLOW};
}}
#AppTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {C.ACCENT_LIGHT};
    letter-spacing: 1.5px;
}}
#AppSubtitle {{
    font-size: 11px;
    color: {C.FG_DIM};
    letter-spacing: 0.5px;
}}
#ModeBadge {{
    background: {C.ACCENT_SOFT};
    color: {C.ACCENT_LIGHT};
    border: 1px solid {C.ACCENT_DEEP};
    border-radius: 10px;
    padding: 2px 12px;
    font-size: 11px;
    font-weight: 600;
}}

/* 卫星类型胶囊徽章(容器) */
#SatBadge {{
    background: {C.BG_PANEL_2};
    border: 1px solid {C.GOLD};
    border-radius: 14px;
    padding: 0px;
}}
#SatBadge QComboBox {{
    background: transparent;
    border: none;
    color: {C.GOLD};
    padding: 2px 8px 2px 12px;
    font-size: 12px;
    font-weight: 600;
}}
#SatBadge QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
#SatBadge QComboBox::down-arrow {{
    width: 8px;
    height: 8px;
}}

/* 信息徽章(算法库/模板/数据包) */
QLabel#InfoChip {{
    color: {C.FG_DIM};
    background: {C.BG_PANEL_2};
    border: 1px solid {C.BORDER};
    border-radius: 12px;
    padding: 2px 12px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#InfoChip[loaded="true"] {{
    color: {C.OK};
    background: {C.OK_SOFT};
    border: 1px solid {C.OK};
    font-weight: 600;
}}

/* 控制栏分组分隔标签(左侧青色竖条) */
#GroupSep {{
    color: {C.ACCENT_LIGHT};
    background: {C.BG_PANEL_2};
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    padding: 3px 12px 3px 14px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    border-left: 3px solid {C.ACCENT};
}}

/* ---------- 控制区 ---------- */
#ControlBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL}, stop:1 {C.BG_APP});
    border-bottom: 1px solid {C.BORDER_SOFT};
}}

QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL_2}, stop:1 {C.BG_PANEL});
    color: {C.FG};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 14px;
    min-height: 26px;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.3px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL_3}, stop:1 {C.BG_PANEL_2});
    border-color: {C.ACCENT};
    color: {C.ACCENT_LIGHT};
}}
QPushButton:pressed {{
    background: {C.BG_PANEL_2};
    border-color: {C.ACCENT_DEEP};
}}
QPushButton:disabled {{
    color: {C.FG_FAINT};
    background: {C.BG_TABLE};
    border-color: {C.BORDER_SOFT};
}}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.ACCENT}, stop:1 {C.ACCENT_DEEP});
    border: 1px solid {C.ACCENT_LIGHT};
    color: {C.BG_APP};
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.ACCENT_LIGHT}, stop:1 {C.ACCENT});
    border-color: {C.ACCENT_LIGHT};
    color: #ffffff;
}}
QPushButton#Danger {{
    background: {C.ERR_SOFT};
    border: 1px solid #8a3346;
    color: #ff9db0;
}}
QPushButton#Danger:hover {{
    background: #552433;
    border-color: {C.ERR};
    color: #ffffff;
}}
QPushButton#SecondaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #14314a, stop:1 #0f2438);
    border: 1px solid {C.ACCENT_DEEP};
    color: {C.ACCENT_LIGHT};
    font-weight: 600;
}}
QPushButton#SecondaryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a4263, stop:1 #14314a);
    border-color: {C.ACCENT};
    color: #ffffff;
}}

/* ---------- 下拉框(全局) ---------- */
QComboBox {{
    background: {C.BG_PANEL_2};
    color: {C.FG};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 22px;
    font-size: 12px;
    font-weight: 500;
    selection-background-color: {C.BG_TABLE_SEL};
}}
QComboBox:hover {{
    border-color: {C.ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.FG_DIM};
    margin-right: 6px;
}}
QComboBox:hover::down-arrow {{
    border-top-color: {C.ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {C.BG_PANEL};
    color: {C.FG};
    border: 1px solid {C.BORDER_GLOW};
    selection-background-color: {C.ACCENT_SOFT};
    selection-color: {C.ACCENT_LIGHT};
    outline: none;
}}

/* ---------- 时间编辑框(全局) ---------- */
QDateTimeEdit {{
    background: {C.BG_PANEL_2};
    color: {C.FG};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 22px;
    font-size: 12px;
    font-family: {FONT_MONO};
    selection-background-color: {C.ACCENT_SOFT};
}}
QDateTimeEdit:hover {{
    border-color: {C.ACCENT};
}}
QDateTimeEdit::drop-down {{
    border: none;
    width: 22px;
}}
QDateTimeEdit::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.FG_DIM};
    margin-right: 6px;
}}
QDateTimeEdit:hover::down-arrow {{
    border-top-color: {C.ACCENT};
}}

/* ---------- 工具按钮(导出下拉等) ---------- */
QToolButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL_2}, stop:1 {C.BG_PANEL});
    color: {C.FG};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 14px;
    min-height: 26px;
    font-size: 12px;
    font-weight: 500;
}}
QToolButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL_3}, stop:1 {C.BG_PANEL_2});
    border-color: {C.ACCENT};
    color: {C.ACCENT_LIGHT};
}}
QToolButton:pressed {{
    background: {C.BG_PANEL_2};
    border-color: {C.ACCENT_DEEP};
}}
QToolButton:disabled {{
    color: {C.FG_FAINT};
    background: {C.BG_TABLE};
    border-color: {C.BORDER_SOFT};
}}
QToolButton::menu-indicator {{
    image: none;
    width: 10px;
    margin-right: 4px;
}}
QToolButton::menu-arrow {{
    image: none;
    width: 0;
}}

/* ---------- Tab ---------- */
QTabWidget::pane {{
    border: none;
    background: {C.BG_APP};
    top: -1px;
}}
QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {C.FG_DIM};
    border: none;
    padding: 10px 24px;
    margin-right: 2px;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QTabBar::tab:hover {{
    color: {C.FG};
    background: {C.BG_PANEL_2};
    border-radius: 4px 4px 0 0;
}}
QTabBar::tab:selected {{
    color: {C.ACCENT_LIGHT};
    background: {C.ACCENT_SOFT};
    border-bottom: 2px solid {C.ACCENT};
    border-radius: 4px 4px 0 0;
}}

/* ---------- 表格 ---------- */
QTableView {{
    background: {C.BG_TABLE};
    border: 1px solid {C.BORDER_SOFT};
    border-radius: 8px;
    gridline-color: #1c2740;
    selection-background-color: {C.BG_TABLE_SEL};
    selection-color: {C.FG};
    alternate-background-color: {C.BG_TABLE_ALT};
}}
QTableView::item {{
    padding: 2px 6px;
    border: none;
}}
QTableView::item:selected {{
    background: {C.BG_TABLE_SEL};
}}
QHeaderView::section {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {C.BG_PANEL_3}, stop:1 {C.BG_PANEL});
    color: {C.ACCENT_LIGHT};
    border: none;
    border-right: 1px solid {C.BORDER_SOFT};
    border-bottom: 1px solid {C.BORDER};
    padding: 4px 8px;
    font-weight: 700;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background: {C.BG_PANEL_3};
    border: none;
}}

/* ---------- 卡片/标签 ---------- */
#Card {{
    background: {C.BG_PANEL};
    border: 1px solid {C.BORDER_SOFT};
    border-radius: 10px;
}}
#CardTitle {{
    color: {C.ACCENT_LIGHT};
    font-size: 12px;
    font-weight: 600;
}}
#CardValue {{
    color: {C.FG};
    font-size: 22px;
    font-weight: 700;
}}
#CardValueMono {{
    color: {C.FG};
    font-size: 18px;
    font-weight: 700;
    font-family: {FONT_MONO};
}}
#SectionTitle {{
    color: {C.ACCENT_LIGHT};
    font-size: 14px;
    font-weight: 700;
}}
#HintLabel {{
    color: {C.FG_FAINT};
    font-size: 12px;
}}

/* ---------- 状态条 ---------- */
QStatusBar {{
    background: {C.BG_PANEL};
    color: {C.FG_DIM};
    border-top: 1px solid {C.BORDER_SOFT};
}}
QStatusBar QLabel {{
    color: {C.FG_DIM};
    padding: 0 8px;
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2c3c5c;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C.ACCENT_DEEP};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2c3c5c;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C.ACCENT_DEEP};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: #101828;
    border: 1px solid {C.BORDER_SOFT};
    border-radius: 6px;
    text-align: center;
    color: {C.FG};
    height: 16px;
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C.ACCENT_DEEP}, stop:1 {C.ACCENT});
    border-radius: 5px;
}}

/* ---------- 菜单 ---------- */
QMenu {{
    background: {C.BG_PANEL};
    color: {C.FG};
    border: 1px solid {C.BORDER_GLOW};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {C.ACCENT_SOFT};
    color: {C.ACCENT_LIGHT};
}}

/* ---------- 工具提示 ---------- */
QToolTip {{
    background: {C.BG_PANEL_3};
    color: {C.FG};
    border: 1px solid {C.ACCENT_DEEP};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""
