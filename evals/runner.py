"""HTTP 黑盒评测跑分（SPEC 16 / PRD FR-601~603）。

用法（在 dainshang2 根目录）：
  uv run python evals/runner.py --base-url http://127.0.0.1:18083 --tag v2 --clean
  uv run python evals/runner.py --base-url http://127.0.0.1:18082 --tag v1 --clean

黑盒原则：只通过 /api/chat 交互；--clean 用 SQL 清理会话与退款测试数据（测试夹具，
保证可重复运行，不构成评分耦合）。工具序列等内部指标不做跨版本对比。
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import httpx
import pymysql
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.conf.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REFUND_ID_RE = re.compile(r"R[0-9A-Z]{10,}")
ORDER_ID_RE = re.compile(r"\b[ABC]\d{11}\b")


def norm(text: str) -> str:
    return (text or "").replace(",", "").replace(" ", "").replace("，", "").casefold()


def _db_connect(db: str):
    u = urllib.parse.urlparse(settings.database_url.replace("+aiomysql", "+pymysql"))
    return pymysql.connect(
        host=u.hostname, port=u.port or 3306, user=u.username,
        password=u.password or "", database=db, charset="utf8mb4",
    )


def cleanup(conversation_id: str, order_ids: list[str], scope: str = "both") -> None:
    """清理评测夹具（scope: v2 | v1 | both）——两版并行跑分时互不误伤。"""
    conn = _db_connect("customer_service")
    with conn.cursor() as cur:
        if scope in ("v2", "both"):
            cur.execute(
                "DELETE FROM agent_tool_calls WHERE run_id IN "
                "(SELECT id FROM (SELECT id FROM agent_runs WHERE conversation_id=%s) t)",
                (conversation_id,),
            )
            cur.execute("DELETE FROM agent_runs WHERE conversation_id=%s", (conversation_id,))
            cur.execute("DELETE FROM chat_messages WHERE conversation_id=%s", (conversation_id,))
        if scope in ("v1", "both"):
            cur.execute("DELETE FROM dialogue_states WHERE sender_id=%s", (conversation_id,))
    conn.commit()
    conn.close()
    if order_ids:
        conn = _db_connect("commerce")
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(order_ids))
            cur.execute(f"DELETE FROM refund_requests WHERE order_id IN (SELECT id FROM orders WHERE order_id IN ({fmt}))",
                        order_ids)
        conn.commit()
        conn.close()


def evaluate(expect: dict, bot_texts: list[str]) -> tuple[bool, list[str]]:
    """规则断言：全部通过返回 (True, [])，否则返回 (False, 失败明细)。"""
    details: list[str] = []
    full = "\n".join(bot_texts)
    final = bot_texts[-1] if bot_texts else ""
    n_full, n_final = norm(full), norm(final)

    def _check(name: str, ok: bool, hint: str = "") -> None:
        if not ok:
            details.append(f"{name}{('：' + hint) if hint else ''}")

    for p in expect.get("final_regex", []):
        _check(f"final_regex[{p}]", bool(re.search(p, final or "")))
    for p in expect.get("final_not_regex", []):
        _check(f"final_not_regex[{p}]", not re.search(p, final or ""))
    for k in expect.get("final_contains_all", []):
        _check(f"final_contains_all[{k}]", norm(k) in n_final)
    keys_any = expect.get("final_contains_any", [])
    if keys_any:
        # 组内任一命中即过（bug 修复：此前误写成逐项 must-all）
        _check(f"final_contains_any{keys_any}", any(norm(k) in n_final for k in keys_any))
    for group in expect.get("final_contains_groups", []):
        _check(f"final_contains_groups[{group}]", any(norm(k) in n_final for k in group))
    for k in expect.get("final_not_contains", []):
        _check(f"final_not_contains[{k}]", norm(k) not in n_final)
    for group in expect.get("any_turn_contains_all", []):
        _check(f"any_turn_contains_all[{group}]",
               any(all(norm(k) in norm(t) for k in group) for t in bot_texts))
    for k in expect.get("any_turn_contains_any", []):
        _check(f"any_turn_contains_any[{k}]", any(norm(k) in norm(t) for t in bot_texts))
    for kw in expect.get("asks_question_with", []):
        _check(
            f"asks_question_with[{kw}]",
            any(("？" in t or "?" in t) and norm(kw) in norm(t) for t in bot_texts[:-1])  # 反问应发生在中间轮
            or any(("？" in t or "?" in t) and norm(kw) in norm(t) for t in bot_texts),
        )
    return (not details, details)


def run_case(client: httpx.Client, case: dict, clean: bool, scope: str = "both") -> dict:
    user = case["user"]
    order_ids = sorted(set(ORDER_ID_RE.findall(json.dumps(case["turns"], ensure_ascii=False))))
    if clean:
        cleanup(user, order_ids, scope)

    transcript: list[dict] = []
    for idx, turn in enumerate(case["turns"], 1):
        payload: dict = {"sender_id": user, "msg_id": f"{case['id']}-{idx}"}
        if turn.get("text"):
            payload["text"] = turn["text"]
        if turn.get("object"):
            payload["object"] = turn["object"]
        bot_texts: list[str] = []
        err = None
        for attempt in range(2):  # 网络级失败重试 1 次
            try:
                resp = client.post("/api/chat", json=payload, timeout=180)
                try:
                    body = resp.json()
                except Exception:
                    # 记录非 JSON 响应体（如 V1 内部错误的 HTML/空体），便于归因
                    raise RuntimeError(f"HTTP {resp.status_code} 非 JSON 响应: {resp.text[:120]}")
                bot_texts = [
                    m.get("text") or ""
                    for m in body.get("msgs", [])
                    if m.get("text")
                ]
                err = None
                break
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"[:150]
                time.sleep(3)
        transcript.append({
            "turn": idx,
            "user": turn.get("text") or f"[卡片:{(turn.get('object') or {}).get('id')}]",
            "bot": bot_texts,
            "error": err,
        })

    bot_texts_all = [t for tr in transcript for t in tr["bot"]]
    rule_pass, rule_details = (False, ["无 bot 回复"]) if not bot_texts_all else evaluate(case["expect"], bot_texts_all)
    return {
        "id": case["id"], "dimension": case["dimension"], "user": user,
        "transcript": transcript, "rule_pass": rule_pass, "rule_details": rule_details,
        "judge": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "dataset.yaml"))
    parser.add_argument("--clean", action="store_true", help="每条用例前清理会话与退款测试数据")
    parser.add_argument("--scope", default="both", choices=["v2", "v1", "both"],
                        help="清理范围：两版并行跑分时各清各的（v1 只清 dialogue_states）")
    parser.add_argument("--only", default=None, help="只跑某维度（调试用）")
    args = parser.parse_args()

    cases = yaml.safe_load(Path(args.dataset).read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["dimension"] == args.only]

    results = []
    t0 = time.time()
    with httpx.Client(base_url=args.base_url) as client:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case['id']} ({case['dimension']}) ...", flush=True)
            try:
                results.append(run_case(client, case, args.clean, args.scope))
            except Exception as exc:  # noqa: BLE001——单例失败不中断全量
                print("   FAILED:", exc, flush=True)
                results.append({
                    "id": case["id"], "dimension": case["dimension"], "user": case["user"],
                    "transcript": [], "rule_pass": False,
                    "rule_details": [f"runner 异常: {type(exc).__name__}: {exc}"[:150]], "judge": None,
                })
            mark = "PASS" if results[-1]["rule_pass"] else "FAIL"
            print(f"   -> {mark}", flush=True)

    by_dim: dict[str, dict] = {}
    for r in results:
        d = by_dim.setdefault(r["dimension"], {"pass": 0, "total": 0})
        d["total"] += 1
        d["pass"] += int(r["rule_pass"])

    out = {
        "tag": args.tag, "base_url": args.base_url,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_min": round((time.time() - t0) / 60, 1),
        "by_dimension": by_dim,
        "overall": {"pass": sum(d["pass"] for d in by_dim.values()),
                    "total": sum(d["total"] for d in by_dim.values())},
        "cases": results,
    }
    out_path = ROOT / "evals" / f"results_{args.tag}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n== 完成：规则断言 {out['overall']['pass']}/{out['overall']['total']}，"
          f"耗时 {out['elapsed_min']} 分钟 → {out_path}")


if __name__ == "__main__":
    main()
