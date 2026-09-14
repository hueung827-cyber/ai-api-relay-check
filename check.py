#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI API 渠道质量检测脚本（可复现 / 可自行修改）

用途：验证一个 OpenAI 兼容 API 渠道的可用率、延迟、模型一致性、计费口径。
开源目的：让"选哪家中转站"这件事从"听宣传"变成"看数据"。

用法：
    python check.py --base https://example.com/v1 --key sk-xxx --model claude-sonnet-4-5
    python check.py --base https://xyutoken.cc/api/v1 --key 你的令牌 --model claude-sonnet-4-5 --n 100

依赖：
    pip install requests
    pip install tiktoken        # 可选，用于计费偏差检测

许可证：MIT
"""

import argparse
import json
import statistics
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("缺少依赖，请先执行：pip install requests")


# ---------------------------------------------------------------- 基础请求
def chat(base, key, model, messages, max_tokens=64, timeout=60, stream=False):
    """发一次 chat/completions 请求，返回 (是否成功, 耗时ms, 响应dict或错误信息)"""
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if stream:
        payload["stream"] = True

    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        ms = (time.time() - t0) * 1000
        if r.status_code != 200:
            return False, ms, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, ms, r.json()
    except Exception as e:
        return False, (time.time() - t0) * 1000, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- 检测 1：可用率与延迟
def check_availability(base, key, model, n=50, interval=0.3):
    print(f"\n{'='*60}")
    print(f"【检测1】可用率与延迟  （样本 {n} 次）")
    print(f"{'='*60}")

    ok_list, fail_list = [], []
    for i in range(n):
        ok, ms, resp = chat(base, key, model,
                            [{"role": "user", "content": "hi"}], max_tokens=5)
        (ok_list if ok else fail_list).append(ms if ok else resp)
        bar = "█" * int((i + 1) / n * 30)
        print(f"\r  {bar:<30} {i+1}/{n}", end="", flush=True)
        time.sleep(interval)
    print()

    total = n
    rate = len(ok_list) / total * 100

    print(f"\n  可用率     : {rate:.2f}%   ({len(ok_list)}/{total})")
    if ok_list:
        ok_sorted = sorted(ok_list)
        p50 = statistics.median(ok_sorted)
        p95 = ok_sorted[min(int(len(ok_sorted) * 0.95), len(ok_sorted) - 1)]
        print(f"  延迟 中位数: {p50:.0f} ms")
        print(f"  延迟 P95   : {p95:.0f} ms")
        print(f"  延迟 最大  : {max(ok_sorted):.0f} ms")
        if p50 > 0 and p95 / p50 > 3:
            print("  ⚠️  P95 是中位数的 3 倍以上 → 存在抖动，可能为共享池")
        if rate < 99:
            print(f"  ⚠️  可用率低于 99% → 不建议用于生产环境")
        else:
            print("  ✅ 可用率良好")
    if fail_list:
        print(f"\n  失败样本（前 3 条）:")
        for f in fail_list[:3]:
            print(f"    - {f}")

    return {"rate": rate, "latency": ok_list}


# ---------------------------------------------------------------- 检测 2：模型一致性
PROBES = [
    "用一句话解释什么是哈希表，不要使用任何比喻。",
    "把这句话改成被动语态：工程师修复了这个 bug。",
    "1 到 100 之间有多少个质数？只回答数字。",
]


def check_model_consistency(base, key, model, repeat=3):
    print(f"\n{'='*60}")
    print(f"【检测2】模型一致性（同题采样 {repeat} 次）")
    print(f"{'='*60}")

    outputs = {}
    for probe in PROBES:
        print(f"\n  ▸ Probe: {probe[:36]}...")
        outs = []
        for i in range(repeat):
            ok, ms, resp = chat(base, key, model,
                                [{"role": "user", "content": probe}],
                                max_tokens=128, timeout=90)
            if ok:
                txt = resp["choices"][0]["message"]["content"].strip()
                outs.append(txt)
                print(f"    [{i+1}] {txt[:70]}{'...' if len(txt) > 70 else ''}")
            else:
                print(f"    [{i+1}] ❌ {resp}")
            time.sleep(0.5)
        outputs[probe] = outs

    print("\n  【怎么读结果】")
    print("    · 多次输出风格一致（句长/术语/格式稳定）→ 大概率是同一个真模型")
    print("    · 风格忽而啰嗦忽而简短、术语习惯跳变 → 后端可能在多模型间轮换")
    print("    · 想更严格：把同一 probe 在官方渠道跑一遍做对照")
    return outputs


# ---------------------------------------------------------------- 检测 3：计费偏差
def check_billing(base, key, model, prompt=None):
    print(f"\n{'='*60}")
    print(f"【检测3】计费口径偏差（本地 tokenizer vs 返回 usage）")
    print(f"{'='*60}")

    try:
        import tiktoken
    except ImportError:
        print("  ⏭️  未安装 tiktoken，跳过。安装：pip install tiktoken")
        return None

    prompt = prompt or "请用 200 字介绍 Python 的 GIL 机制，并说明它对多线程的影响。"
    enc = tiktoken.get_encoding("cl100k_base")
    local_tokens = len(enc.encode(prompt))

    ok, ms, resp = chat(base, key, model,
                        [{"role": "user", "content": prompt}], max_tokens=300, timeout=120)
    if not ok:
        print(f"  ❌ 请求失败: {resp}")
        return None

    usage = resp.get("usage") or {}
    reported = usage.get("prompt_tokens")
    if reported is None:
        print("  ⚠️  响应里没有 usage 字段，无法核对")
        return None

    dev = abs(reported - local_tokens) / local_tokens * 100
    print(f"  本地理论 prompt tokens : {local_tokens}")
    print(f"  服务商返回 prompt tokens: {reported}")
    print(f"  偏差                    : {dev:.1f}%")
    if dev < 10:
        print("  ✅ 偏差在合理范围（不同 tokenizer 本身有差异）")
    elif dev < 20:
        print("  🟡 偏差略大，建议确认计费口径是否包含系统提示词")
    else:
        print("  ⚠️  偏差过大，建议向服务商追问计费方式")
    print(f"\n  完整 usage: {json.dumps(usage, ensure_ascii=False)}")
    return {"local": local_tokens, "reported": reported, "deviation": dev}


# ---------------------------------------------------------------- 检测 4：长上下文
def check_context(base, key, model, repeat_times=8000):
    print(f"\n{'='*60}")
    print(f"【检测4】长上下文验证（约 {repeat_times*5//1000}K+ 字符输入）")
    print(f"{'='*60}")

    long_text = "测试内容。" * repeat_times
    prompt = f"{long_text}\n\n上面这段文字里'测试'出现了多少次？只回答数字。"
    print(f"  输入长度: {len(prompt):,} 字符")

    ok, ms, resp = chat(base, key, model,
                        [{"role": "user", "content": prompt}],
                        max_tokens=50, timeout=180)
    if ok:
        ans = resp["choices"][0]["message"]["content"].strip()
        print(f"  耗时: {ms:.0f} ms")
        print(f"  回答: {ans[:100]}")
        print(f"  期望次数: {repeat_times}")
        print("\n  【怎么读】")
        print("    · 数字接近 → 长上下文正常")
        print("    · 报 context length exceeded 但长度远小于宣传值 → 窗口被压缩")
        print("    · 答非所问/明显截断 → 中间内容被丢弃")
    else:
        print(f"  ❌ 失败: {resp}")
        print("  → 若报错提到 context length，说明实际窗口可能小于宣传值")

    return ok


# ---------------------------------------------------------------- 主流程
def main():
    p = argparse.ArgumentParser(description="AI API 渠道质量检测")
    p.add_argument("--base", required=True, help="API 地址，如 https://example.com/v1")
    p.add_argument("--key", required=True, help="API 令牌")
    p.add_argument("--model", required=True, help="模型名，如 claude-sonnet-4-5")
    p.add_argument("--n", type=int, default=50, help="可用率检测样本数（默认 50）")
    p.add_argument("--skip", default="", help="跳过的检测，逗号分隔：availability,consistency,billing,context")
    p.add_argument("--json-out", default="", help="把结果写入 JSON 文件")
    args = p.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    print("=" * 60)
    print("  AI API 渠道质量检测")
    print(f"  地址: {args.base}")
    print(f"  模型: {args.model}")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = {"base": args.base, "model": args.model, "time": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 连通性预检
    ok, ms, resp = chat(args.base, args.key, args.model,
                        [{"role": "user", "content": "ping"}], max_tokens=5)
    if not ok:
        print(f"\n❌ 连通性检查失败: {resp}")
        print("   请检查：① Base URL 是否需要 /v1  ② 令牌是否正确  ③ 模型名是否存在")
        sys.exit(1)
    print(f"\n✅ 连通性 OK（{ms:.0f} ms）")

    if "availability" not in skip:
        result["availability"] = check_availability(args.base, args.key, args.model, n=args.n)
    if "consistency" not in skip:
        result["consistency"] = check_model_consistency(args.base, args.key, args.model)
    if "billing" not in skip:
        result["billing"] = check_billing(args.base, args.key, args.model)
    if "context" not in skip:
        result["context_ok"] = check_context(args.base, args.key, args.model)

    print(f"\n{'='*60}")
    print("  检测完成")
    print(f"{'='*60}")

    if args.json_out:
        # 延迟列表太长，导出时截断
        slim = dict(result)
        if isinstance(slim.get("availability"), dict):
            slim["availability"] = {k: v for k, v in slim["availability"].items() if k != "latency"}
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=2)
        print(f"  结果已写入: {args.json_out}")


if __name__ == "__main__":
    main()
