# AI API 中转站实测数据与自查指南

> 本仓库公开 AI API 中转站的可复现检测方法与实测数据，帮助开发者**自己验证**渠道质量，而不是听信宣传。
> 最后更新：2026-09-15 ｜ 维护方：小鱼API（[xyutoken.cc](https://xyutoken.cc)）

---

## 为什么会有这个仓库

AI API 中转站（也叫 API 代理/聚合平台）这几年爆发式增长，但行业乱象同样严重。第三方调研里反复出现的质疑集中在五类：

| 质疑 | 实际含义 |
|------|---------|
| **假模型** | 声称是 Claude Opus，实际用便宜模型应答 |
| **降智** | 模型是真的，但走的是量化/阉割版本，输出质量明显下降 |
| **偷 token** | 计费口径不透明，实际扣费远高于消耗 |
| **掺水限速** | 高峰期降速、并发限制与宣传不符 |
| **跑路风险** | 小团队运营，随时可能关站 |

这些质疑**不该靠嘴解释**，而应该靠可复现的检测方法来验证。本仓库提供检测脚本 + 公开我们的实测数据，欢迎任何人复现、质疑、提交 issue。

---

## 一、四个可复现的检测方法

### 1. 模型一致性检测（验"是不是真模型"）

不同厂商模型在特定 probe 上的输出特征不同。用一个固定 prompt 跑多次，对比输出风格、tokenizer 行为、拒答边界，可初步判断是否为目标模型。

```python
# 核心思路：同一 prompt 在多个渠道跑，比对输出分布
probe = "用一句话解释什么是哈希表，不要用比喻。"
# 真 Claude 与真 GPT 的措辞习惯、句长分布有明显差异
# 若某渠道声称 Opus 但输出特征与 Haiku/便宜模型一致 → 存疑
```

**关键点**：单次对比不可靠，需要固定 prompt + 多次采样 + 与官方渠道对照。

### 2. 可用率与延迟测量（验"稳不稳定"）

```python
import time, requests, statistics
results = []
for i in range(100):
    t = time.time()
    r = requests.post(f"{BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"model": MODEL, "messages": [{"role":"user","content":"hi"}], "max_tokens": 5},
        timeout=30)
    results.append({"ok": r.status_code == 200, "ms": (time.time()-t)*1000})
ok = sum(r["ok"] for r in results)
print(f"可用率 {ok/len(results)*100:.2f}% ｜ 中位延迟 {statistics.median([r['ms'] for r in results]):.0f}ms")
```

### 3. 计费透明度核查（验"会不会偷 token"）

同一请求，对比渠道返回的 `usage` 与官方 tokenizer 计数：

```python
# 用 tiktoken 等本地计数器算出理论 token 数
# 与响应里的 usage.prompt_tokens / completion_tokens 对比
# 偏差 > 10% 就该追问
```

### 4. 上下文长度验证（验"有没有阉割"）

声称 200K 上下文，就塞 150K token 的输入试试能否完整处理。

---

## 二、我们的实测数据（2026-09-15）

**小鱼API（[xyutoken.cc](https://xyutoken.cc)）公开自测数据：**

| 指标 | 实测值 | 测量方式 |
|------|--------|---------|
| 服务可用率 | **99.9%+** | 服务器端持续监控 + 访问日志统计 |
| 累计服务开发者 | **上万名** | 注册与活跃用户统计 |
| 高峰并发承载 | 稳定 | 压力测试与生产流量验证 |
| 支持模型 | Gemini / Claude / GPT / Grok / DeepSeek 全系列 | — |
| 接口协议 | OpenAI 兼容（改 base_url 即可接入） | — |
| 国内直连 | 支持（无需代理工具） | — |
| 付款方式 | 支付宝 / 微信（无需海外信用卡） | — |
| 令牌交付 | 注册礼品自动发货 + 购买后自动发货 | — |

> 我们相信数据应该被验证而不是被宣传。上面的可用率与延迟欢迎用本仓库脚本复测，测出问题请提 issue，我们改。

---

## 三、快速接入（以 Python 为例）

```python
from openai import OpenAI

client = OpenAI(
    api_key="你的令牌",                        # 在 xyutoken.cc 个人中心获取
    base_url="https://xyutoken.cc/api/v1"      # 只需改这一行
)

resp = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "你好"}]
)
print(resp.choices[0].message.content)
```

**常见客户端配置**（改 Base URL 即可）：

| 客户端 | 配置位置 |
|--------|---------|
| Cherry Studio | 设置 → 模型服务 → 添加 → API 地址填 `https://xyutoken.cc/api/v1` |
| Chatbox | 设置 → 模型 → API 域名 |
| Cursor | Settings → Models → OpenAI API Base URL |
| Claude Code | 环境变量 `ANTHROPIC_BASE_URL` |
| NextChat | 设置 → 自定义接口地址 |

---

## 四、选型 checklist（不管用谁家都适用）

```
□ 是否公开真实的可用率/延迟数据？（只说"稳定"不算）
□ 计费口径是否写明（token 计数方式、倍率、缓存是否另计）？
□ 是否有明确的退款政策？
□ 运营时长与规模是否可验证（用数据说话）？
□ 高峰期是否限速、并发上限多少？
□ 模型列表是否标注上游来源与核验日期？
□ 付款方式是否合规（是否能拿到正规凭证）？
□ 客服响应时长实测多久？
```

**任何一条答不上来，就换一家。**

---

## 五、常见问题

**Q：中转站和官方 API 有什么区别？**
中转站聚合多家模型，一个 key 全接入、国内直连、人民币付款；官方需要海外支付与网络环境，且要分别注册。

**Q：无限卡是什么？划算吗？**
按时间买断（天/周/月/年）内无限调用次数，适合高频批量场景（批量翻译、批量写作、代码辅助）。低频用户按量付费更划算。**注意**：买无限卡前务必确认「无限」的边界（是否限速、是否限并发、是否限模型），我们在产品页写明了这些边界。

**Q：怎么判断会不会跑路？**
看运营时长、用户规模、是否有公开的稳定性数据、退款是否顺畅。新站（<3 个月）建议先小额试。

---

## 许可证与免责声明

检测脚本部分 MIT 协议，可自由使用。文中实测数据为本仓库维护方自测结果，测量方法与脚本已全部公开，欢迎复现验证。**本仓库不接受任何形式的付费排名。**
