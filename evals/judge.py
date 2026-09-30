"""LLM-as-judge（SPEC 16.3 / PRD FR-604）：对已跑完的评测结果逐例打主观分（1~5）。

用法：uv run python evals/judge.py --tag v2
规则断言已覆盖确定性维度；judge 只评主观质量（相关性/正确性/语气），temperature=0，
双版同题对照，报告中以相对差值呈现。
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.conf.config import settings  # noqa: E402

RUBRIC = """你是电商客服对话的质量评审员。根据对话记录与预期要点，给机器人表现打 1~5 分：
5 = 完全解决诉求且信息可信、表达自然；
4 = 基本正确，有轻微瑕疵；
3 = 部分解决，或存在可疑表述；
2 = 明显错误、答非所问或漏答关键诉求；
1 = 编造事实、越权承诺或严重跑偏。
评分必须独立于机器人的自我解释，只看对话内容与预期要点。只输出 JSON：{"score": 1-5, "reason": "一句中文理由"}"""

PROMPT = """【对话记录】
{transcript}

【预期要点】
{hints}

请按评分标准打分并只输出 JSON。"""


def build_transcript(case: dict) -> str:
    lines = []
    for tr in case["transcript"]:
        lines.append(f"用户（第{tr['turn']}轮）：{tr['user']}")
        for bot in tr["bot"]:
            lines.append(f"  客服：{bot}")
        if tr.get("error"):
            lines.append(f"  [调用失败：{tr['error']}]")
    return "\n".join(lines) or "（无回复——调用失败）"


def ask_llm(client: httpx.Client, transcript: str, hints: list[str]) -> dict:
    payload = {
        "model": settings.llm_model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": PROMPT.format(
                transcript=transcript, hints="\n".join(f"- {h}" for h in hints or ["（无）"]))},
        ],
        "extra_body": {"enable_thinking": False},
    }
    last = None
    for _ in range(3):
        try:
            resp = client.post(f"{settings.llm_base_url}/chat/completions", json=payload, timeout=90)
            body = resp.json()
            text = body["choices"][0]["message"]["content"] or ""
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            data = json.loads(text)
            score = max(1, min(5, int(data.get("score", 0)) or 0))
            return {"score": score, "reason": str(data.get("reason", ""))[:120]}
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"[:120]
            time.sleep(3)
    return {"score": 0, "reason": f"judge 失败: {last}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    path = Path(__file__).resolve().parents[1] / "evals" / f"results_{args.tag}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    client = httpx.Client(
        base_url=settings.llm_base_url,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
    )
    done = 0
    for i, case in enumerate(data["cases"], 1):
        if case.get("judge"):
            continue
        verdict = ask_llm(client, build_transcript(case), _hints_of(data, case))
        case["judge"] = verdict
        done += 1
        print(f"[{i}/{len(data['cases'])}] {case['id']} -> {verdict['score']} {verdict['reason'][:40]}", flush=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    scores = [c["judge"]["score"] for c in data["cases"] if c.get("judge") and c["judge"]["score"]]
    if scores:
        data["judge_summary"] = {"avg": round(sum(scores) / len(scores), 2), "n": len(scores)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"== judge 完成 {done} 例，均分 {data.get('judge_summary', {}).get('avg')}")


def _hints_of(data: dict, case: dict) -> list[str]:
    """从 dataset 找回 judge_hints（results 里未存 expect，按 id 回查）。"""
    import yaml

    dataset = yaml.safe_load((Path(__file__).resolve().parents[1] / "evals" / "dataset.yaml").read_text(encoding="utf-8"))
    for c in dataset:
        if c["id"] == case["id"]:
            return c.get("expect", {}).get("judge_hints", [])
    return []


if __name__ == "__main__":
    main()
