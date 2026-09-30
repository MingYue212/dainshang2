"""对比报告生成（SPEC 16 / PRD FR-605）：读取 results_v1.json + results_v2.json → docs/eval-report.md。

用法：uv run python evals/report.py
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIM_NAMES = {
    "normal": "正常路径", "missing_slot": "缺槽位反问", "interrupt": "打断恢复",
    "multi_intent": "多意图混合", "adversarial": "越界与诱导", "chitchat_knowledge": "闲聊与知识",
}


def load(tag: str) -> dict | None:
    p = ROOT / "evals" / f"results_{tag}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def judge_avg(data: dict | None, dim: str | None = None) -> float | None:
    if not data:
        return None
    scores = [c["judge"]["score"] for c in data["cases"]
              if c.get("judge") and c["judge"]["score"] > 0
              and (dim is None or c["dimension"] == dim)]
    return round(sum(scores) / len(scores), 2) if scores else None


def main() -> None:
    v1, v2 = load("v1"), load("v2")
    if not v2:
        print("缺少 results_v2.json"); return

    lines = [
        "# V1（workflow 版） vs V2（智能体版）· 评测对比报告",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}　|　",
        f"> V1: {v1['base_url'] if v1 else '未运行'}（{v1['ran_at'] if v1 else '-'}）　|　",
        f"> V2: {v2['base_url']}（{v2['ran_at']}）",
        ">",
        "> 判分口径：**规则断言**（工具结果可验证的确定性事实：退款单号/订单状态/金额/越界拒绝，可复现、零成本）",
        "> + **LLM-judge**（主观质量 1~5 分，temperature=0，双版同题对照看相对差值）。",
        "> 工具调用序列为 V2 内部指标（agent_tool_calls 快照），不参与跨版本公平对比。",
        "",
        "## 一、总体结果",
        "",
        "| 版本 | 规则断言通过 | 通过率 | judge 均分 |",
        "|---|---|---|---|",
    ]

    for tag, data in (("V1", v1), ("V2", v2)):
        if not data:
            lines.append(f"| {tag} | - | - | - |")
            continue
        o = data["overall"]
        rate = f"{o['pass'] / o['total'] * 100:.0f}%" if o["total"] else "-"
        ja = judge_avg(data)
        lines.append(f"| {tag} | {o['pass']}/{o['total']} | {rate} | {ja if ja is not None else '-'} |")

    lines += ["", "## 二、分维度对比", "",
              "| 维度 | V1 断言 | V2 断言 | V1 judge | V2 judge |", "|---|---|---|---|---|"]
    dims = list(v2["by_dimension"].keys())
    for dim in dims:
        name = DIM_NAMES.get(dim, dim)
        def cell(data, dim, key):
            if not data or dim not in data["by_dimension"]:
                return "-"
            d = data["by_dimension"][dim]
            return f"{d['pass']}/{d['total']}" if key == "rule" else (judge_avg(data, dim) or "-")
        lines.append(f"| {name} | {cell(v1, dim, 'rule')} | {cell(v2, dim, 'rule')} | "
                     f"{cell(v1, dim, 'judge')} | {cell(v2, dim, 'judge')} |")

    lines += ["", "## 三、亮点用例摘录（V2 transcript 节选）", ""]
    highlights = {"A01": "幻觉拦截：诱导把退款金额改成 5000", "M02": "缺原因反问：有单号没原因只问原因",
                  "I02": "打断恢复：中途查另一单物流后接回退款", "A07": "越权拒绝：无取消工具不假装取消"}
    for case in v2["cases"]:
        if case["id"] not in highlights:
            continue
        snippet = ""
        for tr in case["transcript"]:
            if tr["bot"]:
                snippet = tr["bot"][-1][:100]
                break
        lines.append(f"- **{case['id']}**（{highlights[case['id']]}，规则断言 {'PASS' if case['rule_pass'] else 'FAIL'}）：{snippet}")

    lines += ["", "## 四、逐例明细（规则断言失败项）", ""]
    for tag, data in (("V1", v1), ("V2", v2)):
        if not data:
            continue
        lines.append(f"### {tag}")
        fails = [c for c in data["cases"] if not c["rule_pass"]]
        if not fails:
            lines.append("- 全部通过")
        for c in fails:
            lines.append(f"- `{c['id']}`（{DIM_NAMES.get(c['dimension'])}）：{'；'.join(c['rule_details'])}")
        lines.append("")

    out = ROOT / "docs" / "eval-report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已生成 → {out}")


if __name__ == "__main__":
    main()
