#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日新闻推送：
- arXiv AI 论文（cs.AI / cs.CL / cs.LG）
- 知乎科技热榜
- B站科技区热门视频

生成暗色 HTML 卡片，通过 PushPlus 推送。
"""
import json
import os
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

PUSHPLUS_API = "https://www.pushplus.plus/send"
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "").strip()

SECTIONS = [
    ("arxiv", "arXiv AI 论文", "最新发布的人工智能、机器学习、计算语言学论文"),
    ("juejin", "掘金热榜", "掘金上受关注的技术文章"),
    ("bilibili", "B站科技热门", "B站科技/编程相关的热门视频"),
]


def http_get(url: str, headers: dict | None = None, is_json: bool = True) -> Any:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        data = r.read()
    if is_json:
        return json.loads(data.decode("utf-8", errors="ignore"))
    return data.decode("utf-8", errors="ignore")


def fetch_arxiv() -> list[dict]:
    """抓取昨天至今的 arXiv AI 相关论文"""
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    categories = "cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV"
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=cat:{categories}&submittedDate:[{yesterday}0000+TO+{yesterday}2359]"
        "&sortBy=submittedDate&sortOrder=descending&max_results=15"
    )
    text = http_get(url, is_json=False)
    root = ET.fromstring(text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).replace("\n", " ").strip()
        summary = entry.findtext("atom:summary", "", ns).replace("\n", " ").strip()
        link = entry.find("atom:link[@rel='alternate']", ns)
        url = link.get("href") if link is not None else ""
        items.append({
            "title": title,
            "summary": summary[:800],
            "url": url,
            "source": "arXiv",
        })
    return items[:10]


def fetch_juejin() -> list[dict]:
    """抓取掘金热榜，筛选科技/AI/编程相关文章"""
    url = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    data = http_get(url, headers=headers, is_json=True)
    items = []
    tech_keywords = re.compile(
        r"AI|人工智能|大模型|LLM|GPT|ChatGPT|DeepSeek|Claude|"
        r"算法|编程|代码|GitHub|开源|Python|JavaScript|Rust|Go|"
        r"前端|后端|全栈|开发|"
        r"数据库|云原生|中间件|"
        r"机器学习|深度学习|NLP|视觉|CV|",
        re.I,
    )
    for item in data.get("data", []):
        content = item.get("content", {})
        title = content.get("title", "").strip()
        content_id = content.get("content_id", "")
        if not title or not content_id:
            continue
        url = f"https://juejin.cn/post/{content_id}"
        desc = content.get("brief", "")[:200]
        is_tech = bool(tech_keywords.search(title))
        items.append({
            "title": title,
            "summary": desc,
            "url": url,
            "source": "掘金",
            "is_tech": is_tech,
        })
    tech = [i for i in items if i.pop("is_tech")]
    others = [i for i in items if i not in tech]
    return (tech + others)[:10]


def fetch_bilibili() -> list[dict]:
    """抓取 B站综合热门，筛选科技/编程相关视频"""
    url = "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
    }
    data = http_get(url, headers=headers, is_json=True)
    items = []
    tech_tids = {188, 36, 95, 122, 124}  # 科技、知识、编程/计算机科学相关
    tech_keywords = re.compile(
        r"AI|人工智能|大模型|LLM|GPT|ChatGPT|DeepSeek|Claude|"
        r"算法|编程|代码|GitHub|开源|Python|JavaScript|Rust|Go|"
        r"教程|学习|",
        re.I,
    )
    for item in data.get("data", {}).get("list", []):
        title = item.get("title", "").strip()
        bvid = item.get("bvid", "")
        url = item.get("short_link_v2") or item.get("short_link") or f"https://www.bilibili.com/video/{bvid}"
        author = item.get("owner", {}).get("name", "")
        tid = item.get("tid", 0)
        tname = item.get("tname", "")
        desc = item.get("desc", "")[:200]
        is_tech = tid in tech_tids or bool(tech_keywords.search(title))
        if not is_tech:
            continue
        summary = f"UP主：{author}。{tname}区。{desc}".strip()
        items.append({
            "title": title,
            "summary": summary,
            "url": url,
            "source": "B站",
        })
        if len(items) >= 10:
            break
    return items


def ai_summarize(items: list[dict], section_key: str) -> dict[str, str]:
    """为每个条目生成 30-50 字中文摘要"""
    if not AI_API_KEY or not AI_MODEL:
        print(f"[WARN] {section_key}: AI 未配置，跳过 AI 摘要")
        return {}

    summaries: dict[str, str] = {}
    batch_size = 10
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        payload = [
            {"title": it["title"], "summary": it.get("summary", "")[:400], "source": it.get("source", "")}
            for it in batch
        ]
        prompt = (
            "你是中国技术新闻编辑，请为下面每个条目写一句中文简介。"
            "严格要求：1.纯中文，不出现英文句子；"
            "2.每条 30-50 个汉字；3.说清楚它是什么、为什么值得关注；"
            "4.自然地道，不要‘值得一看’这种套话；"
            "5.输出严格 JSON，键是条目标题（原样保留），值是中文简介。"
        )
        try:
            payload_json = json.dumps(
                {
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是中文技术新闻编辑，只输出纯中文 JSON。"},
                        {"role": "user", "content": f"{prompt}\n\n{json.dumps(payload, ensure_ascii=False)}"},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 2000,
                },
                ensure_ascii=False,
            )
            req = urllib.request.Request(
                f"{AI_BASE_URL}/chat/completions",
                data=payload_json.encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode("utf-8", errors="ignore"))
            content = resp["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.S)
            parsed = json.loads(content)
            count = 0
            for k, v in parsed.items():
                if isinstance(v, str) and v.strip():
                    summaries[str(k)] = v.strip()
                    count += 1
            print(f"[DEBUG] {section_key} batch {i//batch_size + 1}: parsed {count} summaries")
        except Exception as exc:
            print(f"[WARN] {section_key} batch {i//batch_size + 1} 失败：{exc}")
    return summaries


def fallback_summary(item: dict) -> str:
    return "热门条目，点击查看详情。"


def html_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_html(data: dict[str, list[dict]]) -> str:
    now = datetime.now().strftime("%m-%d %H:%M")

    section_htmls = []
    for key, title, subtitle in SECTIONS:
        items = data.get(key, [])
        if not items:
            continue
        summaries = ai_summarize(items, key)
        cards = []
        for idx, item in enumerate(items, 1):
            summary = html_escape(summaries.get(item["title"]) or fallback_summary(item))
            meta = html_escape(f"{item.get('source', '')}")
            cards.append(f"""
  <div class="card">
    <div class="rank">{idx}</div>
    <div class="content">
      <a href="{item['url']}" class="item-title">{html_escape(item['title'])}</a>
      <div class="meta">{meta}</div>
      <p class="desc">{summary}</p>
    </div>
  </div>""")
        section_htmls.append(f"""
  <div class="section">
    <div class="section-title">{title}</div>
    <div class="section-subtitle">{subtitle}</div>
    {''.join(cards)}
  </div>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  body{{margin:0;padding:0;background:#0c0c0e;font-family:'Geist',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased;}}
  .wrap{{max-width:720px;margin:0 auto;padding:48px 24px;}}
  .hero{{position:relative;background:linear-gradient(160deg,#18181c 0%,#111114 60%,#0d0d0f 100%);border:1px solid rgba(255,255,255,0.06);border-radius:32px;padding:42px 36px;margin-bottom:32px;overflow:hidden;}}
  .hero::before{{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.12),transparent);}}
  .kicker{{font-size:11px;font-weight:700;letter-spacing:0.22em;color:#6b7280;text-transform:uppercase;margin-bottom:16px;}}
  .hero h1{{margin:0;font-size:42px;font-weight:800;color:#fafafa;letter-spacing:-0.04em;line-height:1.05;}}
  .hero p{{margin:14px 0 0 0;font-size:16px;color:#9ca3af;font-weight:500;max-width:520px;}}
  .section{{margin-bottom:42px;}}
  .section-title{{font-size:24px;font-weight:800;color:#fafafa;margin-bottom:6px;letter-spacing:-0.02em;}}
  .section-subtitle{{font-size:14px;color:#6b7280;margin-bottom:20px;}}
  .card{{position:relative;background:#141417;border:1px solid rgba(255,255,255,0.05);border-radius:24px;padding:24px;margin-bottom:14px;display:flex;gap:18px;align-items:flex-start;}}
  .card::after{{content:'';position:absolute;top:0;left:24px;right:24px;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.06),transparent);}}
  .rank{{font-size:34px;font-weight:800;color:#8b5cf6;line-height:1;min-width:42px;text-align:left;letter-spacing:-0.05em;}}
  .content{{flex:1;min-width:0;}}
  .item-title{{font-size:17px;font-weight:700;color:#f3f4f6;margin-bottom:8px;text-decoration:none;display:block;letter-spacing:-0.01em;}}
  .meta{{font-size:12px;font-weight:600;color:#6b7280;margin-bottom:10px;}}
  .desc{{margin:0;font-size:14px;color:#d1d5db;line-height:1.75;}}
  .footer{{text-align:center;padding:24px 0 0 0;}}
  .footer a{{color:#52525b;font-size:13px;text-decoration:none;font-weight:500;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="kicker">Daily Tech Digest</div>
    <h1>每日科技精选</h1>
    <p>arXiv AI 论文 · 知乎科技热榜 · B站科技热门，每条一句中文精读。生成时间：{now} 北京时间</p>
  </div>
  {''.join(section_htmls)}
  <div class="footer">
    <a href="https://github.com/heijiao211-star/meirixinwen-tuisong">来源：heijiao211-star/meirixinwen-tuisong</a>
  </div>
</div>
</body>
</html>"""


def push(title: str, content: str) -> None:
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("缺少 PUSHPLUS_TOKEN")
    payload = {"token": token, "title": title, "content": content, "template": "html"}
    if topic := os.getenv("PUSHPLUS_TOPIC", "").strip():
        payload["topic"] = topic
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(PUSHPLUS_API, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8", errors="ignore"))
        print(f"[INFO] pushplus response: {resp}")
        if resp.get("code") not in (None, 200):
            raise RuntimeError(f"PushPlus 返回异常：{resp}")


def main():
    print("[INFO] fetching arxiv...")
    arxiv_items = fetch_arxiv()
    print(f"[INFO] arxiv items: {len(arxiv_items)}")

    print("[INFO] fetching juejin...")
    juejin_items = fetch_juejin()
    print(f"[INFO] juejin items: {len(juejin_items)}")

    print("[INFO] fetching bilibili...")
    bilibili_items = fetch_bilibili()
    print(f"[INFO] bilibili items: {len(bilibili_items)}")

    data = {"arxiv": arxiv_items, "juejin": juejin_items, "bilibili": bilibili_items}
    html = build_html(data)

    with open("latest_report.html", "w", encoding="utf-8") as f:
        f.write(html)

    title = f"每日科技精选 {datetime.now().strftime('%m-%d')}"
    push(title, html)
    print("[INFO] 推送完成")


if __name__ == "__main__":
    main()
