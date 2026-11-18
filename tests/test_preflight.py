"""前置检查契约的反向守卫（对应 SKILL.md 同名小节）。

技能在本环境运行，数据与模型都由宿主提供；所以 SKILL.md 必须先要求一次前置检查，
且不得再出现任何"技能自己准备数据/模型"的符号。少了这条约束，收件人会直接跳到
取数或评测，把「没权限」当成「没行情」继续算，结论静默失真。
"""
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")


def test_preflight_section_exists_and_covers_mcp_and_model():
    i = TEXT.find("## 前置检查")
    assert i >= 0, "SKILL.md 必须有前置检查小节"
    j = TEXT.find("\n## ", i + 5)
    block = TEXT[i:j if j > 0 else len(TEXT)]
    for need in ("auth_status", "reauth_required", "import pytest"):
        assert need in block, f"前置检查缺少 {need}"
    # 脚本是纯标准库（requirements.txt 声明无三方依赖），所以 pandas 不是前置条件。
    # 旧文本把它当依赖，是在一台没装 pandas 的机器上把一条永远过不了的检查写成闸门。
    assert "import pandas" not in block, "前置检查不应要求 pandas：脚本只用标准库"
    assert "无三方依赖" in block or "标准库" in block, "必须写明脚本只用标准库"
    assert "模型" in block and ("agent" in block or "宿主" in block), "必须说明模型由宿主提供"
    assert "停止" in block and ("缺" in block or "报告" in block), "必须写明不过就停并报告缺什么"


def test_preflight_precedes_everything_executable():
    """前置检查必须排在所有可执行流程之前，否则等于没有。"""
    i = TEXT.find("## 前置检查")
    for later in ("python3 scripts/", "```bash"):
        k = TEXT.find(later)
        assert k == -1 or k > i, f"{later} 出现在前置检查之前"


def test_skill_never_prepares_its_own_data_or_model():
    forbidden = (r"CONSTRAINT" + "_LLM", r"OPENAI" + "_API_KEY", r"ANTHROPIC" + "_API_KEY",
                 r"init" + "_token", r"import panda" + "_data")
    hits = [p for p in forbidden if re.search(p, TEXT)]
    assert not hits, "SKILL.md 出现自备数据/模型的符号：" + ", ".join(hits)
