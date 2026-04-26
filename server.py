# -*- coding: utf-8 -*-
"""
短视频素材收集分析平台 V6.9 社媒助手上报诊断修复版
Python 3.14 / 标准库 / 无需 pip install

运行：python server.py
访问：http://127.0.0.1:8000
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
COVER_DIR = DATA_DIR / "covers"
VIDEO_DIR = DATA_DIR / "videos"
DB_PATH = DATA_DIR / "app.db"
HOST = "127.0.0.1"
PORT = 8000

DATA_DIR.mkdir(exist_ok=True)
COVER_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "英语学习", "教育知识", "商业营销", "美妆护肤", "美食探店", "旅行户外", "健身运动",
    "家居生活", "剧情情感", "母婴亲子", "影视娱乐", "科技AI", "账号拆解", "爆款案例", "其他"
]
STATUSES = ["待处理", "已分类", "已分析", "已改写", "已加入选题", "已制作", "已发布", "已废弃"]
PLATFORMS = ["抖音", "小红书", "视频号", "快手", "B站", "微博", "本地视频", "微信视频", "其他"]

KEYWORDS = {
    "英语学习": ["英语", "单词", "口语", "语法", "雅思", "托福", "四六级", "wolf", "down", "vocabulary", "english"],
    "教育知识": ["学习", "老师", "课堂", "知识", "教育", "课程", "考试", "方法", "技巧"],
    "商业营销": ["营销", "商业", "成交", "转化", "私域", "引流", "带货", "销售", "老板"],
    "美妆护肤": ["美妆", "护肤", "口红", "粉底", "面膜", "穿搭", "妆容"],
    "美食探店": ["美食", "探店", "好吃", "餐厅", "火锅", "小吃", "甜品"],
    "旅行户外": ["旅行", "旅游", "景点", "露营", "徒步", "城市", "酒店"],
    "健身运动": ["健身", "减脂", "运动", "训练", "肌肉", "瑜伽", "跑步"],
    "家居生活": ["家居", "装修", "收纳", "好物", "生活", "厨房", "卧室"],
    "剧情情感": ["剧情", "反转", "情感", "恋爱", "夫妻", "分手", "故事"],
    "母婴亲子": ["宝宝", "孩子", "育儿", "亲子", "妈妈", "母婴"],
    "影视娱乐": ["电影", "电视剧", "综艺", "明星", "娱乐", "剪辑"],
    "科技AI": ["AI", "人工智能", "ChatGPT", "软件", "工具", "编程", "自动化"],
}


# ------------------------- 基础工具 -------------------------

def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                platform TEXT,
                title TEXT,
                author TEXT,
                author_url TEXT,
                cover_url TEXT NOT NULL,
                video_file_url TEXT,
                description TEXT,
                raw_copy TEXT,
                transcript TEXT,
                ai_summary TEXT,
                ai_analysis TEXT,
                rewritten_copy TEXT,
                category TEXT,
                content_type TEXT,
                usage_type TEXT,
                heat_level TEXT,
                tags TEXT,
                status TEXT,
                project TEXT,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                play_count INTEGER DEFAULT 0,
                publish_time TEXT,
                source_method TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS failed_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                platform TEXT,
                title TEXT,
                raw_copy TEXT,
                reason TEXT,
                created_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_collects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                normalized_url TEXT,
                content_key TEXT,
                platform TEXT,
                title TEXT,
                raw_input TEXT,
                status TEXT,
                last_error TEXT,
                material_id INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                material_id INTEGER,
                reference_author TEXT,
                rewritten_copy TEXT,
                shot_form TEXT,
                storyboard TEXT,
                status TEXT,
                publish_platform TEXT,
                final_url TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS reporting_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT,
                message TEXT,
                inserted_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                raw_body TEXT,
                parsed_preview TEXT,
                created_at TEXT
            )
            """
        )
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('strict_cover','1')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto_collect_pending','1')")
        c.commit()


init_db()


def esc(x: Any) -> str:
    return html.escape(str(x or ""), quote=True)


def parse_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    s = str(value).strip().lower().replace(",", "").replace(" ", "")
    if not s or s in {"-", "--", "未知", "none", "null"}:
        return 0
    mult = 1
    if "万" in s or s.endswith("w"):
        mult = 10000
        s = s.replace("万", "").replace("w", "")
    elif "亿" in s:
        mult = 100000000
        s = s.replace("亿", "")
    elif s.endswith("k"):
        mult = 1000
        s = s[:-1]
    s = re.sub(r"[^0-9.]", "", s)
    try:
        return int(float(s) * mult) if s else 0
    except Exception:
        return 0


def fmt_count(n: Any) -> str:
    n = parse_int(n)
    if n >= 100000000:
        return f"{n/100000000:.1f}亿".rstrip("0").rstrip(".")
    if n >= 10000:
        return f"{n/10000:.1f}万".rstrip("0").rstrip(".")
    return str(n) if n else "-"


def detect_platform(url: str, text: str = "") -> str:
    s = (url + " " + text).lower()
    if "douyin" in s or "iesdouyin" in s:
        return "抖音"
    if "xiaohongshu" in s or "xhslink" in s or "xhs" in s:
        return "小红书"
    if "channels.weixin" in s or "weixin.qq" in s:
        return "视频号"
    if "kuaishou" in s or "gifshow" in s:
        return "快手"
    if "bilibili" in s or "b23.tv" in s or re.search(r"\bBV[0-9A-Za-z]+", s):
        return "B站"
    if "weibo" in s:
        return "微博"
    return "其他"


def extract_first_url(text: str) -> str:
    m = re.search(r"https?://[^\s，。；;）)】\]]+", text or "")
    return m.group(0).rstrip(" .。") if m else ""


def strip_url_from_text(text: str) -> str:
    return re.sub(r"https?://[^\s，。；;）)】\]]+", "", text or "").strip()


def clean_share_title(text: str) -> str:
    """把普通用户复制的分享口令清洗成更像标题/文案的文本。"""
    s = strip_url_from_text(text or "")
    s = re.sub(r"复制此链接.*$", "", s, flags=re.I).strip()
    s = re.sub(r"打开(?:Dou音|抖音|小红书|快手|B站).*?$", "", s, flags=re.I).strip()
    s = re.sub(r"^[0-9.]+\s+[0-9]{1,2}/[0-9]{1,2}\s+[^:：]{1,12}[:：]\s*", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip(" -_，,。；;")
    return s[:220]


def text_fingerprint_for_match(text: str) -> set[str]:
    """用于校验自动采集是否采到同一条视频。
    只取中文/英文/数字字符，去掉平台口令和短链接，避免推荐页误采。
    """
    cleaned = clean_share_title(text or "")
    cleaned = re.sub(r"#[^#\s，。；;:：、/|]+", "", cleaned)
    chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned.lower())
    return {c for c in chars if c.strip()}


def auto_capture_matches_pending(pending_raw: str, pending_title: str, collected_title: str, transcript: str) -> tuple[bool, str]:
    """后台/自动采集必须和待采集口令有足够重合，防止把推荐页当前视频错入库。"""
    expected = text_fingerprint_for_match((pending_title or "") + " " + (pending_raw or ""))
    if len(expected) < 6:
        return True, "待采集文本太短，跳过相似度校验"
    got = text_fingerprint_for_match((collected_title or "") + " " + (transcript or ""))
    overlap = len(expected & got)
    need = max(4, min(10, int(len(expected) * 0.18)))
    if overlap >= need:
        return True, f"自动校验通过：重合字符 {overlap}/{len(expected)}"
    return False, f"自动采集疑似采错视频：分享文本与页面内容重合度过低（{overlap}/{len(expected)}）。请打开正确视频详情页后使用插件“手动采集当前页面”。"


def extract_tags(text: str) -> list[str]:
    tags = []
    for m in re.finditer(r"#([^#\s，。；;:：、/|]+)", text or ""):
        tag = m.group(1).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:12]


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url)
        scheme = p.scheme or "https"
        host = p.netloc.lower()
        path = re.sub(r"/+$", "", p.path or "/") or "/"
        qs = urllib.parse.parse_qs(p.query)
        keep: list[tuple[str, str]] = []
        for k in ["aweme_id", "modal_id", "id", "bvid", "noteId", "vid"]:
            if k in qs and qs[k]:
                keep.append((k, qs[k][-1]))
        query = urllib.parse.urlencode(keep)
        return urllib.parse.urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return url


def content_key_from_text(text: str) -> str:
    text = text or ""
    patterns = [
        r"(BV[0-9A-Za-z]+)",
        r"douyin\.com/.{0,80}?/video/(\d+)",
        r"aweme_id=(\d+)",
        r"xiaohongshu\.com/.{0,120}?/(?:explore|discovery/item|item)/(\w+)",
        r"channels\.weixin\.qq\.com/.{0,120}?/(?:feed|finder/.{0,80}?feedId=)([A-Za-z0-9_\-]+)",
        r"(?:kuaishou|gifshow)\.com/.{0,120}?/(?:short-video|f)/([A-Za-z0-9_\-]+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    url = extract_first_url(text) or text.strip()
    try:
        pu = urllib.parse.urlparse(url)
        return f"{pu.netloc.lower()}{re.sub(r'/+$','', pu.path or '/')}"[:220]
    except Exception:
        return url[:220]


# ------------------------- 分类与 AI -------------------------

def classify(title: str, desc: str = "", tags: str = "") -> str:
    s = ((title or "") + " " + (desc or "") + " " + (tags or "")).lower()
    best = ("其他", 0)
    for cat, words in KEYWORDS.items():
        score = sum(1 for w in words if w.lower() in s)
        if score > best[1]:
            best = (cat, score)
    return best[0]


def heat_level(like_count: int, collect_count: int, share_count: int) -> str:
    if like_count >= 100000 or share_count >= 10000 or collect_count >= 20000:
        return "近期爆款"
    if like_count >= 10000 or share_count >= 1000 or collect_count >= 5000:
        return "高收藏/高赞素材"
    if like_count >= 1000:
        return "普通素材"
    return "待观察"


def infer_content_type(cat: str, text: str) -> str:
    if "英语" in cat or "教育" in cat:
        return "知识教学"
    if "商业" in cat:
        return "带货/营销"
    if "剧情" in cat:
        return "剧情短片"
    return "短视频素材"


def make_summary(data: dict[str, Any]) -> str:
    title = data.get("title") or "该素材"
    cat = data.get("category") or "其他"
    return f"这是一条来自{data.get('platform') or '未知平台'}的{cat}素材，标题为「{title}」，可用于选题参考、文案拆解和二次创作。"


def ai_rewrite(material: sqlite3.Row, style: str) -> str:
    title = material["title"] or ""
    transcript = material["transcript"] or material["description"] or title
    style = style or "抖音爆款版"
    base = transcript or title
    if style == "小红书种草版":
        return f"【{title}】\n\n今天刷到这个内容真的很适合收藏。\n它最有价值的点是：用一个很直观的例子，把复杂信息讲得很容易懂。\n\n我的改写思路：\n1. 先用一句话制造好奇心；\n2. 再给出生活化解释；\n3. 最后加一个可以马上使用的例子。\n\n参考文案：\n{base}\n\n适合标签：#{material['category']} #选题参考 #短视频文案"
    if style == "视频号知识版":
        return f"大家好，今天分享一个很实用的知识点：{title}。\n\n这条内容的核心不在于信息有多复杂，而在于表达方式足够清楚。\n我们可以按照三个步骤来讲：第一，提出问题；第二，解释概念；第三，给出案例。\n\n原始参考：{base}\n\n如果你觉得有帮助，可以收藏起来，后面慢慢看。"
    if style == "口播脚本版":
        return f"你知道吗？{title}，很多人第一反应都会理解错。\n\n今天我用最简单的方法给你讲明白：\n{base}\n\n记住这个画面，下次你就不会再忘。"
    if style == "分镜脚本版":
        return f"选题：{title}\n\n镜头1：近景开场，人物直接抛出反常识问题。\n字幕：你以为它是这个意思？其实完全不是。\n\n镜头2：切到示意画面，展示核心概念。\n旁白：{base[:120]}\n\n镜头3：用一个生活化场景举例。\n字幕：记住这个画面，就能记住这个表达。\n\n镜头4：结尾引导。\n字幕：想看同系列，评论区告诉我。"
    if style == "卖课引流版":
        return f"很多人学不会，不是因为笨，而是因为记忆方法错了。\n\n比如这个内容：{title}\n\n普通讲法只告诉你答案，但真正有效的讲法，是让你看到画面、理解逻辑、马上能用。\n\n参考内容：{base}\n\n我把这类高频知识点整理成了一套系统方法，想要资料可以留言「资料」。"
    if style == "评论区互动版":
        return f"你第一次看到「{title}」会想到什么？\n\n很多人第一反应都会理解错。\n其实它真正的记忆点在这里：{base[:160]}\n\n你还想让我拆哪个知识点？打在评论区。"
    return f"你知道吗？「{title}」最容易被人理解错。\n\n别死记硬背，记住这个画面就够了：\n{base}\n\n一句话总结：把抽象知识变成画面，记得更快，也更不容易忘。\n\n想看更多同类拆解，先收藏，后面慢慢学。"


def ai_analyze(material: sqlite3.Row) -> str:
    title = material["title"] or ""
    cat = material["category"] or "其他"
    likes = fmt_count(material["like_count"])
    tags = material["tags"] or ""
    return f"""爆款原因分析：
1. 选题明确：标题「{title}」能让用户快速判断内容价值。
2. 类目聚焦：属于「{cat}」，适合持续做系列化内容。
3. 数据参考：当前点赞 {likes}，可作为热度判断依据。
4. 标签可复用：{tags or '暂无标签，建议补充关键词标签'}。

内容结构拆解：
- 开头：用问题、误解或利益点抓住注意力。
- 主体：用例子解释核心信息，降低理解成本。
- 结尾：给出收藏、评论或系列化关注引导。

可模仿方向：
1. 保留原选题逻辑，替换成自己的案例。
2. 改写成口播脚本，适合真人出镜。
3. 拆成分镜脚本，适合 AI 视频生成。
4. 延展同系列选题，形成账号内容资产。"""


# ------------------------- 抓取与入库 -------------------------

def absolute_url(url: str, base: str) -> str:
    if not url:
        return ""
    return urllib.parse.urljoin(base, html.unescape(url))


def meta_value(page: str, key: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+itemprop=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']{re.escape(key)}["\']',
    ]
    for p in patterns:
        m = re.search(p, page, re.I | re.S)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def title_from_html(page: str) -> str:
    t = meta_value(page, "og:title") or meta_value(page, "twitter:title") or meta_value(page, "title")
    if not t:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        if m:
            t = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
    t = re.sub(r"[_\-—|｜].{0,18}(抖音|小红书|快手|哔哩哔哩|Bilibili|微博).*$", "", t or "", flags=re.I).strip()
    return t


def fetch_url(url: str, timeout: int = 12) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        data = resp.read(3_000_000)
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            text = data.decode(charset, errors="ignore")
        except Exception:
            text = data.decode("utf-8", errors="ignore")
        return final_url, text


def fetch_bilibili_by_bvid(bvid: str) -> dict[str, Any]:
    api = f"https://api.bilibili.com/x/web-interface/view?bvid={urllib.parse.quote(bvid)}"
    req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or "B站接口读取失败")
    d = data.get("data", {})
    stat = d.get("stat", {})
    owner = d.get("owner", {})
    return {
        "url": f"https://www.bilibili.com/video/{bvid}",
        "platform": "B站",
        "title": d.get("title") or "B站视频",
        "author": owner.get("name") or "",
        "author_url": f"https://space.bilibili.com/{owner.get('mid')}" if owner.get("mid") else "",
        "cover_url": d.get("pic") or "",
        "description": d.get("desc") or "",
        "raw_copy": d.get("desc") or d.get("title") or "",
        "transcript": d.get("desc") or "",
        "like_count": parse_int(stat.get("like")),
        "comment_count": parse_int(stat.get("reply")),
        "collect_count": parse_int(stat.get("favorite")),
        "share_count": parse_int(stat.get("share")),
        "play_count": parse_int(stat.get("view")),
        "publish_time": dt.datetime.fromtimestamp(d.get("pubdate", 0)).strftime("%Y-%m-%d %H:%M") if d.get("pubdate") else "",
        "source_method": "bilibili_api",
    }


def first_count(text: str, labels: list[str]) -> int:
    for label in labels:
        for p in [rf"{label}\s*[:：]?\s*([0-9.]+\s*[万亿kKwW]?)", rf"([0-9.]+\s*[万亿kKwW]?)\s*{label}"]:
            m = re.search(p, text)
            if m:
                return parse_int(m.group(1))
    return 0


def enrich_material(data: dict[str, Any], raw: str = "") -> dict[str, Any]:
    tags = data.get("tags") or ",".join(extract_tags(raw + " " + (data.get("title") or "") + " " + (data.get("description") or "")))
    cat = data.get("category") or classify(data.get("title", ""), (data.get("description", "") + " " + data.get("transcript", "")), tags)
    data["category"] = cat
    data["tags"] = tags
    data["content_type"] = data.get("content_type") or infer_content_type(cat, data.get("title", "") + data.get("description", ""))
    data["usage_type"] = data.get("usage_type") or "选题参考"
    data["heat_level"] = heat_level(parse_int(data.get("like_count")), parse_int(data.get("collect_count")), parse_int(data.get("share_count")))
    data["status"] = data.get("status") or ("已分类" if cat != "其他" else "待处理")
    data["project"] = data.get("project") or "默认素材库"
    data["ai_summary"] = data.get("ai_summary") or make_summary(data)
    data["ai_analysis"] = data.get("ai_analysis") or ""
    data["rewritten_copy"] = data.get("rewritten_copy") or ""
    data["publish_time"] = data.get("publish_time") or ""
    return data


def save_cover_data_url(data_url: str) -> str:
    m = re.match(r"data:image/(png|jpeg|jpg|webp);base64,(.+)", data_url or "", re.I | re.S)
    if not m:
        return ""
    ext = "jpg" if m.group(1).lower() == "jpeg" else m.group(1).lower()
    raw = base64.b64decode(m.group(2))
    digest = hashlib.sha1(raw[:500000] + str(time.time()).encode()).hexdigest()[:20]
    filename = f"cover_{digest}.{ext}"
    path = COVER_DIR / filename
    path.write_bytes(raw)
    return f"/media/covers/{filename}"


def safe_filename(name: str) -> str:
    base = Path(name or "uploaded_video").name
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", base).strip("._")
    return base or "uploaded_video"


def save_video_bytes(filename: str, raw: bytes) -> str:
    if not raw:
        raise ValueError("没有读取到视频文件内容")
    safe = safe_filename(filename)
    ext = Path(safe).suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}:
        ext = ".mp4"
    digest = hashlib.sha1(raw[:1_000_000] + str(len(raw)).encode() + str(time.time()).encode()).hexdigest()[:20]
    out_name = f"video_{digest}{ext}"
    (VIDEO_DIR / out_name).write_bytes(raw)
    return f"/media/videos/{out_name}"


def save_material(data: dict[str, Any]) -> int:
    data = enrich_material(data, data.get("raw_copy") or "")
    fields = [
        "url", "platform", "title", "author", "author_url", "cover_url", "video_file_url", "description", "raw_copy", "transcript",
        "ai_summary", "ai_analysis", "rewritten_copy", "category", "content_type", "usage_type", "heat_level", "tags",
        "status", "project", "like_count", "comment_count", "collect_count", "share_count", "play_count", "publish_time", "source_method"
    ]
    now = now_str()
    vals = {k: data.get(k, "") for k in fields}
    for k in ["like_count", "comment_count", "collect_count", "share_count", "play_count"]:
        vals[k] = parse_int(vals.get(k))
    if not vals.get("cover_url"):
        raise ValueError("严格封面模式：没有封面，不能入库。请使用浏览器采集助手或手动填写封面 URL。")
    with conn() as c:
        existing = c.execute("SELECT id FROM materials WHERE url=?", (vals["url"],)).fetchone()
        if existing:
            set_clause = ",".join([f"{f}=?" for f in fields]) + ",updated_at=?"
            c.execute(f"UPDATE materials SET {set_clause} WHERE id=?", [vals[f] for f in fields] + [now, existing["id"]])
            c.commit()
            return int(existing["id"])
        q = ",".join(fields + ["created_at", "updated_at"])
        placeholders = ",".join(["?"] * (len(fields) + 2))
        cur = c.execute(f"INSERT INTO materials({q}) VALUES({placeholders})", [vals[f] for f in fields] + [now, now])
        c.commit()
        return int(cur.lastrowid)


def record_failed(data: dict[str, Any] | None, reason: str, raw: str = "") -> None:
    data = data or {}
    with conn() as c:
        c.execute(
            "INSERT INTO failed_imports(url,platform,title,raw_copy,reason,created_at) VALUES(?,?,?,?,?,?)",
            (data.get("url") or extract_first_url(raw), data.get("platform") or detect_platform(data.get("url", ""), raw), data.get("title") or "", raw or data.get("raw_copy") or "", reason, now_str()),
        )
        c.commit()


def create_pending_collect(raw: str) -> int:
    url = extract_first_url(raw) or raw.strip()
    platform = detect_platform(url, raw)
    normalized_url = normalize_url(url)
    content_key = content_key_from_text(raw + " " + url)
    title = clean_share_title(raw)[:160] or f"{platform}待补采链接"
    now = now_str()
    with conn() as c:
        existing = c.execute(
            "SELECT id,status FROM pending_collects WHERE ((normalized_url=? AND normalized_url!='') OR (content_key=? AND content_key!='')) ORDER BY id DESC LIMIT 1",
            (normalized_url, content_key),
        ).fetchone()
        if existing and existing["status"] != "已完成":
            c.execute(
                "UPDATE pending_collects SET url=?,normalized_url=?,content_key=?,platform=?,title=?,raw_input=?,status=?,updated_at=? WHERE id=?",
                (url, normalized_url, content_key, platform, title, raw, "待补采", now, existing["id"]),
            )
            c.commit()
            return int(existing["id"])
        cur = c.execute(
            "INSERT INTO pending_collects(url,normalized_url,content_key,platform,title,raw_input,status,last_error,material_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (url, normalized_url, content_key, platform, title, raw, "待补采", "", None, now, now),
        )
        c.commit()
        return int(cur.lastrowid)


def update_pending_collect(pid: int, status: str, last_error: str = "", material_id: int | None = None) -> None:
    if not pid:
        return
    with conn() as c:
        c.execute(
            "UPDATE pending_collects SET status=?,last_error=?,material_id=COALESCE(?,material_id),updated_at=? WHERE id=?",
            (status, last_error, material_id, now_str(), pid),
        )
        c.commit()


def match_pending_collect(url: str, platform: str = "", title: str = "") -> sqlite3.Row | None:
    """只按链接/内容 key 精确匹配。
    旧版按平台兜底会把任意抖音页面错误匹配到待补采任务，导致视频和数据不准确。
    """
    normalized_url = normalize_url(url)
    content_key = content_key_from_text(" ".join([url or "", title or ""]))
    with conn() as c:
        row = c.execute(
            "SELECT * FROM pending_collects WHERE status IN ('待补采','待打开页面','打开中','采集中') AND ((normalized_url=? AND normalized_url!='') OR (content_key=? AND content_key!='')) ORDER BY id DESC LIMIT 1",
            (normalized_url, content_key),
        ).fetchone()
        return row


def get_next_pending_collect() -> sqlite3.Row | None:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM pending_collects WHERE status IN ('待补采','待打开页面') ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row:
            c.execute("UPDATE pending_collects SET status=?,last_error=?,updated_at=? WHERE id=?", ("打开中", "浏览器助手正在后台尝试打开链接", now_str(), row["id"]))
            c.commit()
        return row

def collect_by_link(raw: str) -> tuple[bool, str, dict[str, Any] | None]:
    raw = raw.strip()
    url = extract_first_url(raw) or raw
    if not url.startswith("http"):
        return False, "没有识别到有效链接", None
    platform = detect_platform(url, raw)
    text_without_url = clean_share_title(raw)
    tags = extract_tags(raw)

    try:
        bvid = ""
        m = re.search(r"(BV[0-9A-Za-z]+)", raw)
        if m:
            bvid = m.group(1)
        if not bvid and ("bilibili" in url or "b23.tv" in url):
            final_url, _ = fetch_url(url, timeout=8)
            m = re.search(r"(BV[0-9A-Za-z]+)", final_url)
            if m:
                bvid = m.group(1)
        if bvid:
            data = fetch_bilibili_by_bvid(bvid)
            data["tags"] = ",".join(tags) if tags else ""
            return True, "已通过 B站公开信息读取", enrich_material(data, raw)
    except Exception:
        pass

    try:
        final_url, page = fetch_url(url)
        platform = detect_platform(final_url, raw)
        title = text_without_url or title_from_html(page) or f"{platform}链接素材"
        cover = meta_value(page, "og:image") or meta_value(page, "twitter:image") or meta_value(page, "image")
        desc = meta_value(page, "description") or meta_value(page, "og:description") or text_without_url
        author = meta_value(page, "author") or ""
        plain = re.sub(r"<[^>]+>", " ", page)
        plain = re.sub(r"\s+", " ", html.unescape(plain))[:200000]
        data = {
            "url": final_url,
            "platform": platform,
            "title": title[:160],
            "author": author,
            "author_url": "",
            "cover_url": absolute_url(cover, final_url),
            "description": desc[:1000],
            "raw_copy": raw,
            "transcript": desc[:3000],
            "like_count": first_count(plain, ["点赞", "赞", "获赞", "喜欢"]),
            "comment_count": first_count(plain, ["评论", "弹幕"]),
            "collect_count": first_count(plain, ["收藏", "投币"]),
            "share_count": first_count(plain, ["转发", "分享"]),
            "play_count": first_count(plain, ["播放", "观看"]),
            "publish_time": "",
            "tags": ",".join(tags),
            "source_method": "link_meta",
        }
        data = enrich_material(data, raw)
        if not data.get("cover_url"):
            return False, "平台页面没有公开封面。已进入待补采队列，请打开原平台页面让浏览器助手自动补全。", data
        return True, "已读取公开页面信息", data
    except Exception as e:
        data = {
            "url": url,
            "platform": platform,
            "title": text_without_url[:120] or f"{platform}链接素材",
            "author": "",
            "author_url": "",
            "cover_url": "",
            "description": text_without_url,
            "raw_copy": raw,
            "transcript": text_without_url,
            "like_count": 0,
            "comment_count": 0,
            "collect_count": 0,
            "share_count": 0,
            "play_count": 0,
            "publish_time": "",
            "tags": ",".join(tags),
            "source_method": "link_failed",
        }
        data = enrich_material(data, raw)
        return False, f"链接读取失败：{e}。已进入待补采队列，请用浏览器助手自动补全。", data


# ------------------------- 页面渲染 -------------------------

def page_layout(title: str, body: str, active: str = "") -> bytes:
    menu = [
        ("/", "首页概览"), ("/collect", "链接采集"), ("/materials", "素材库"), ("/authors", "作者/账号库"),
        ("/topics", "选题库"), ("/analytics", "数据看板"), ("/reporting_setup", "数据上报"), ("/settings", "设置"), ("/help", "帮助")
    ]
    nav = "".join(f'<a class="nav {"on" if active==label else ""}" href="{href}">{label}</a>' for href, label in menu)
    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} - 短视频素材收集分析平台</title>
<style>
:root{{--bg:#f3f6fb;--card:#fff;--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--blue:#2563eb;--green:#10b981;--red:#ef4444;--orange:#f97316;--dark:#0f172a}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;font-size:14px}}
a{{color:inherit;text-decoration:none}} .layout{{display:flex;min-height:100vh}} .side{{width:238px;background:#0b1224;color:#e5e7eb;position:fixed;inset:0 auto 0 0;padding:24px 16px}}
.logo{{font-weight:800;font-size:20px;line-height:1.25;margin-bottom:28px}} .nav{{display:block;padding:13px 14px;border-radius:12px;margin:5px 0;color:#cbd5e1;font-weight:700}} .nav:hover,.nav.on{{background:#1e293b;color:#fff}}
.main{{margin-left:238px;width:calc(100% - 238px);padding:28px 36px 60px}} h1{{font-size:30px;margin:0 0 8px}} h2{{font-size:22px;margin:0 0 16px}} h3{{font-size:18px;margin:0 0 12px}} .sub{{color:var(--muted);margin-bottom:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:0 14px 35px rgba(15,23,42,.07);margin-bottom:22px}} .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}} .grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}} .grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
.stat{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}} .stat b{{display:block;font-size:28px;margin-top:8px}} .muted{{color:var(--muted)}} .danger{{color:var(--red)}} .ok{{color:var(--green)}} .warn{{color:var(--orange)}}
input,select,textarea{{width:100%;border:1px solid var(--line);border-radius:12px;padding:12px 14px;font:inherit;background:#fff}} textarea{{min-height:120px;line-height:1.6}} label{{display:block;font-weight:700;margin:10px 0 7px}}
.btn{{display:inline-block;border:0;border-radius:12px;padding:12px 18px;background:#e2e8f0;color:#0f172a;font-weight:800;cursor:pointer}} .btn.blue{{background:var(--blue);color:white}} .btn.green{{background:var(--green);color:white}} .btn.red{{background:var(--red);color:white}} .btn.small{{padding:9px 12px;font-size:13px}} .btn:hover{{filter:brightness(.97)}} .row{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}} .between{{display:flex;align-items:center;justify-content:space-between;gap:12px}}
.materials{{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:18px}} .mcard{{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 8px 25px rgba(15,23,42,.06)}} .cover{{height:178px;background:#e5e7eb;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}} .cover img{{width:100%;height:100%;object-fit:cover;display:block}} .no-cover{{padding:16px;text-align:center;color:#991b1b;background:#fee2e2;border:1px dashed #ef4444;width:100%;height:100%;display:flex;align-items:center;justify-content:center;line-height:1.5}}
.mbody{{padding:16px}} .title{{font-weight:900;font-size:17px;line-height:1.35;margin:6px 0 10px}} .pill{{display:inline-block;padding:5px 9px;border-radius:999px;background:#ecfeff;color:#0369a1;font-size:12px;font-weight:800;margin:3px 5px 3px 0}} .pill.orange{{background:#fff7ed;color:#c2410c}} .pill.green{{background:#ecfdf5;color:#047857}} .pill.gray{{background:#f1f5f9;color:#475569}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}} .metric{{background:#f8fafc;border:1px solid #edf2f7;border-radius:11px;padding:9px;text-align:center}} .metric b{{display:block;font-size:15px}} .metric span{{font-size:12px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse}} th,td{{border-bottom:1px solid var(--line);padding:12px;text-align:left;vertical-align:top}} th{{color:#475569;background:#f8fafc}} .detail-cover{{width:100%;max-height:430px;object-fit:cover;border-radius:18px;border:1px solid var(--line)}} .pre{{white-space:pre-wrap;line-height:1.8;background:#f8fafc;border:1px solid var(--line);border-radius:14px;padding:16px;word-break:break-word}}
.alert{{padding:14px 16px;border-radius:14px;margin:0 0 18px;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8;font-weight:700}} .alert.red{{background:#fef2f2;border-color:#fecaca;color:#b91c1c}} .alert.green{{background:#ecfdf5;border-color:#bbf7d0;color:#047857}}
@media(max-width:900px){{.side{{position:static;width:100%;height:auto}}.layout{{display:block}}.main{{margin-left:0;width:100%;padding:20px}}.grid,.grid2,.grid3{{grid-template-columns:1fr}}}}
</style>
</head><body><div class="layout"><aside class="side"><div class="logo">短视频素材<br>收集分析平台</div>{nav}</aside><main class="main">{body}</main></div></body></html>"""
    return html_doc.encode("utf-8")


def material_card(r: sqlite3.Row) -> str:
    cover = f'<img src="{esc(r["cover_url"])}" alt="封面">' if r["cover_url"] else '<div class="no-cover">未采集到封面<br>请用浏览器采集助手</div>'
    author_link = f'<a class="ok" href="{esc(r["author_url"])}" target="_blank">{esc(r["author"] or "主页")}</a>' if r["author_url"] else esc(r["author"] or "未填写")
    tags = "".join(f'<span class="pill gray">{esc(t.strip())}</span>' for t in (r["tags"] or "").split(",") if t.strip())
    snippet = (r["transcript"] or r["description"] or "")[:70]
    return f"""<div class="mcard">
<div class="cover">{cover}</div>
<div class="mbody">
<div class="muted">{esc(r['platform'])} · {esc(r['publish_time'] or '发布时间未填')} · {esc(r['status'])}</div>
<div class="title">{esc(r['title'])}</div>
<div class="muted">作者：{author_link}</div>
<div class="metrics"><div class="metric"><b>{fmt_count(r['like_count'])}</b><span>点赞</span></div><div class="metric"><b>{fmt_count(r['comment_count'])}</b><span>评论</span></div><div class="metric"><b>{fmt_count(r['collect_count'])}</b><span>收藏</span></div><div class="metric"><b>{fmt_count(r['share_count'])}</b><span>转发</span></div></div>
<div><span class="pill green">{esc(r['category'])}</span><span class="pill orange">{esc(r['heat_level'])}</span></div>
<div style="margin-top:7px">{tags}</div>
<div class="muted" style="margin-top:10px;line-height:1.55">{esc(snippet)}</div>
<div class="row" style="margin-top:14px"><a class="btn small" href="{esc(r['url'])}" target="_blank">打开原平台页</a><a class="btn blue small" href="/material/{r['id']}">详情 / AI</a></div>
</div></div>"""



# ------------------------- 社媒助手数据上报适配 -------------------------

def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ",".join(as_text(x) for x in value if as_text(x))
    if isinstance(value, dict):
        for k in ["url", "src", "value", "text", "name", "title"]:
            if value.get(k):
                return as_text(value.get(k))
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def build_aliases_from_meta(meta: Any) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    if not isinstance(meta, list):
        return aliases
    for m in meta:
        if not isinstance(m, dict):
            continue
        key = as_text(m.get("key"))
        vals = [as_text(m.get("name")), as_text(m.get("alias")), as_text(m.get("description"))]
        if key:
            aliases.setdefault(key, [])
            for v in vals:
                if v and v not in aliases[key]:
                    aliases[key].append(v)
        for v in vals:
            if v:
                aliases.setdefault(v, [])
                if key and key not in aliases[v]:
                    aliases[v].append(key)
    return aliases


def get_from_item(item: dict[str, Any], aliases: dict[str, list[str]], *names: str) -> Any:
    candidates: list[str] = []
    for n in names:
        candidates.append(n)
        candidates.extend(aliases.get(n, []))
    for k in candidates:
        if k in item and item.get(k) not in (None, ""):
            return item.get(k)
    norm = {re.sub(r"[\s_\-]+", "", str(k).lower()): k for k in item.keys()}
    for k in candidates:
        nk = re.sub(r"[\s_\-]+", "", str(k).lower())
        if nk in norm and item.get(norm[nk]) not in (None, ""):
            return item.get(norm[nk])
    return ""


def normalize_social_assistant_item(item: dict[str, Any], meta_aliases: dict[str, list[str]], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    raw_url = as_text(get_from_item(item, meta_aliases,
        "url", "link", "share_url", "video_link", "note_url", "作品链接", "笔记链接", "视频链接", "链接"))
    video_play_url = as_text(get_from_item(item, meta_aliases,
        "video_play_url", "video_url", "download_url", "play_url", "视频播放链接", "视频下载链接", "视频链接"))
    source_url = raw_url or video_play_url or f"social_assistant://{hashlib.sha1(json.dumps(item, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:18]}"
    platform = as_text(get_from_item(item, meta_aliases, "platform", "source", "平台", "来源")) or detect_platform(source_url + " " + as_text(item), "")

    title = as_text(get_from_item(item, meta_aliases,
        "title", "desc", "description", "content", "aweme_desc", "note_title", "视频标题", "笔记标题", "标题", "内容", "笔记内容"))
    content = as_text(get_from_item(item, meta_aliases,
        "content", "desc", "description", "caption", "aweme_desc", "文案", "内容", "笔记内容", "视频文案"))
    if not title:
        title = content[:80] or "社媒助手导入素材"

    author = as_text(get_from_item(item, meta_aliases,
        "user_nickname", "nickname", "author", "author_name", "sec_uid", "博主昵称", "作者", "达人昵称", "发布者"))
    author_url = as_text(get_from_item(item, meta_aliases,
        "user_url", "author_url", "homepage", "author_homepage", "博主主页", "作者主页", "主页链接"))

    cover = get_from_item(item, meta_aliases,
        "note_cover", "cover", "cover_url", "image", "image_url", "pic", "封面", "封面图", "封面图链接")
    if isinstance(cover, list) and cover:
        cover = cover[0]
    cover_url = as_text(cover)
    if not cover_url:
        image_urls = get_from_item(item, meta_aliases, "image_urls", "images", "图片链接", "图片链接数组")
        if isinstance(image_urls, list) and image_urls:
            cover_url = as_text(image_urls[0])
        elif isinstance(image_urls, str) and image_urls.strip():
            parts = re.split(r"[,，\s]+", image_urls.strip())
            cover_url = parts[0] if parts else ""
    if cover_url.startswith("data:image/"):
        saved = save_cover_data_url(cover_url)
        if saved:
            cover_url = saved

    tags_value = get_from_item(item, meta_aliases,
        "tag_list", "tags", "hashtags", "标签", "话题", "笔记话题", "内容标签")
    if isinstance(tags_value, list):
        tags = ",".join(as_text(x).lstrip("#") for x in tags_value if as_text(x))
    else:
        tags = as_text(tags_value).replace("#", ",").strip(", ")
    if not tags:
        tags = ",".join(extract_tags(title + " " + content))

    publish_time = as_text(get_from_item(item, meta_aliases,
        "create_time", "publish_time", "time", "发布时间", "发布日期", "创建时间"))
    update_time = as_text(get_from_item(item, meta_aliases, "update_time", "数据更新时间", "更新时间"))
    content_plus = content + (("\n\n数据更新时间：" + update_time) if update_time else "")

    data = {
        "url": source_url,
        "platform": platform or "其他",
        "title": title[:180],
        "author": author,
        "author_url": author_url,
        "cover_url": cover_url,
        "video_file_url": video_play_url if video_play_url != source_url else "",
        "description": content_plus[:2000],
        "raw_copy": json.dumps(item, ensure_ascii=False),
        "transcript": content_plus[:5000],
        "like_count": parse_int(get_from_item(item, meta_aliases, "liked_count", "like_count", "digg_count", "点赞量", "点赞数")),
        "comment_count": parse_int(get_from_item(item, meta_aliases, "comment_count", "comments", "评论量", "评论数")),
        "collect_count": parse_int(get_from_item(item, meta_aliases, "collected_count", "collect_count", "favorite_count", "收藏量", "收藏数")),
        "share_count": parse_int(get_from_item(item, meta_aliases, "share_count", "forward_count", "转发量", "转发数", "分享量", "分享数")),
        "play_count": parse_int(get_from_item(item, meta_aliases, "play_count", "view_count", "播放量", "浏览量")),
        "publish_time": publish_time,
        "tags": tags,
        "category": classify(title, content_plus, tags),
        "source_method": "social_assistant_reporting",
    }
    return enrich_material(data, data.get("raw_copy") or "")


def parse_reporting_body(raw_text: str, content_type: str = "") -> dict[str, Any]:
    """社媒助手/第三方上报可能是 JSON，也可能是 form-urlencoded 里包了一层 JSON。
    这里尽量宽容解析，避免工具提示“上报成功”但本站拿不到 list。
    """
    raw_text = raw_text or ""
    if not raw_text.strip():
        return {}
    # 1) 直接 JSON
    try:
        obj = json.loads(raw_text)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            return {"list": obj}
    except Exception:
        pass
    # 2) URL encoded: payload=... / data=... / list=...
    try:
        parsed = urllib.parse.parse_qs(raw_text, keep_blank_values=True)
        if parsed:
            flat: dict[str, Any] = {k: (v[-1] if v else "") for k, v in parsed.items()}
            for key in ["payload", "data", "body", "json", "list", "records", "items"]:
                val = flat.get(key)
                if isinstance(val, str) and val.strip():
                    try:
                        inner = json.loads(val)
                        if isinstance(inner, dict):
                            return inner
                        if isinstance(inner, list):
                            return {"list": inner}
                    except Exception:
                        pass
            return flat
    except Exception:
        pass
    return {"raw": raw_text}


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        t = value.strip()
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                return json.loads(t)
            except Exception:
                return value
    return value


def find_reporting_items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    """兼容社媒助手不同版本的数据上报结构。"""
    def as_list(v: Any) -> list[Any]:
        v = _maybe_json(v)
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            # 常见：{list:[...]} / {records:[...]}
            for kk in ["list", "data", "items", "records", "rows", "result"]:
                if kk in v:
                    vv = as_list(v.get(kk))
                    if vv:
                        return vv
            return [v]
        return []

    # 社媒助手文档结构：{extra, meta, list, remark, version}
    meta = _maybe_json(payload.get("meta")) if isinstance(payload, dict) else []
    if not isinstance(meta, list):
        meta = []
    extra = _maybe_json(payload.get("extra")) if isinstance(payload, dict) else {}
    if not isinstance(extra, dict):
        extra = {}

    for key in ["list", "data", "items", "records", "rows", "result", "results", "videos", "notes"]:
        if key in payload:
            arr = as_list(payload.get(key))
            if arr:
                return [x for x in arr if isinstance(x, dict)], meta, extra

    # 有些工具直接上报单条对象，不包 list。
    probable_keys = {"url", "link", "title", "content", "note_cover", "cover", "video_url", "作品链接", "标题", "内容", "封面图"}
    if any(k in payload for k in probable_keys):
        return [payload], meta, extra
    return [], meta, extra


def record_reporting_log(status: str, message: str, raw_body: str, parsed: Any, inserted: int = 0, failed: int = 0) -> None:
    preview = ""
    try:
        preview = json.dumps(parsed, ensure_ascii=False)[:8000]
    except Exception:
        preview = str(parsed)[:8000]
    with conn() as c:
        c.execute(
            "INSERT INTO reporting_logs(status,message,inserted_count,failed_count,raw_body,parsed_preview,created_at) VALUES(?,?,?,?,?,?,?)",
            (status, message, inserted, failed, (raw_body or "")[:200000], preview, now_str()),
        )
        c.commit()

# ------------------------- HTTP Handler -------------------------
class App(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (now_str(), fmt % args))

    def send_bytes(self, data: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Token, Token, Origin, Accept")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {k: v[-1] if v else "" for k, v in parsed.items()}

    def json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}

    def multipart_form(self) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        """轻量级 multipart/form-data 解析器，避免依赖第三方库，兼容 Python 3.14。"""
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', ctype)
        if not m:
            raise ValueError("上传格式错误：没有 multipart boundary")
        boundary = (m.group(1) or m.group(2)).encode("utf-8")
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        fields: dict[str, str] = {}
        files: dict[str, dict[str, Any]] = {}
        for part in raw.split(b"--" + boundary):
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if part.endswith(b"--"):
                part = part[:-2]
            header_blob, sep, body = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            header = header_blob.decode("latin1", errors="ignore")
            name_m = re.search(r'name="([^"]+)"', header)
            if not name_m:
                continue
            name = name_m.group(1)
            body = body.rstrip(b"\r\n")
            fn_m = re.search(r'filename="([^"]*)"', header)
            if fn_m:
                filename = fn_m.group(1) or "uploaded_video"
                ct_m = re.search(r"Content-Type:\s*([^\r\n]+)", header, re.I)
                files[name] = {"filename": filename, "content_type": (ct_m.group(1).strip() if ct_m else "application/octet-stream"), "data": body}
            else:
                fields[name] = body.decode("utf-8", errors="ignore")
        return fields, files

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Token, Token, Origin, Accept")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            if path.startswith("/media/covers/"):
                file = COVER_DIR / Path(path).name
                if file.exists():
                    ctype = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
                    self.send_bytes(file.read_bytes(), content_type=ctype)
                else:
                    self.send_bytes(b"not found", 404, "text/plain")
                return
            if path.startswith("/media/videos/"):
                file = VIDEO_DIR / Path(path).name
                if file.exists():
                    ext = file.suffix.lower()
                    ctype = {".mp4":"video/mp4", ".m4v":"video/mp4", ".mov":"video/quicktime", ".webm":"video/webm", ".avi":"video/x-msvideo", ".mkv":"video/x-matroska"}.get(ext, "application/octet-stream")
                    self.send_bytes(file.read_bytes(), content_type=ctype)
                else:
                    self.send_bytes(b"not found", 404, "text/plain")
                return
            if path == "/":
                return self.index()
            if path == "/collect":
                return self.collect_page(qs)
            if path == "/materials":
                return self.materials(qs)
            if path == "/authors":
                return self.authors()
            if path == "/topics":
                return self.topics()
            if path == "/analytics":
                return self.analytics()
            if path == "/settings":
                return self.settings()
            if path == "/reporting_setup":
                return self.reporting_setup()
            if path == "/help":
                return self.help()
            if path == "/api/pending_match":
                return self.api_pending_match(qs)
            if path == "/api/pending_next":
                return self.api_pending_next()
            m = re.match(r"^/material/(\d+)$", path)
            if m:
                return self.material_detail(int(m.group(1)), qs)
            self.send_bytes(page_layout("404", "<h1>页面不存在</h1>", ""), 404)
        except Exception:
            self.send_bytes(page_layout("错误", f"<div class='alert red'>程序错误</div><pre>{esc(traceback.format_exc())}</pre>", ""), 500)

    def do_PUT(self) -> None:
        # 社媒助手文档支持 POST / PUT / PATCH，这里统一走相同的处理逻辑。
        return self.do_POST()

    def do_PATCH(self) -> None:
        return self.do_POST()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/collect":
                data = self.form()
                raw = data.get("raw", "").strip()
                lines = [x.strip() for x in raw.splitlines() if x.strip()]
                if not lines:
                    self.redirect("/collect?err=" + urllib.parse.quote("请先粘贴链接或分享文本"))
                    return
                ok_count = 0
                pending_count = 0
                last_id = None
                for line in lines:
                    pid = create_pending_collect(line)
                    update_pending_collect(pid, "待打开页面")
                    ok, msg, mat = collect_by_link(line)
                    if ok and mat and mat.get("cover_url"):
                        last_id = save_material(mat)
                        ok_count += 1
                        update_pending_collect(pid, "已完成", "", last_id)
                    else:
                        pending_count += 1
                        update_pending_collect(pid, "待补采", msg)
                        record_failed(mat, msg, line)
                if ok_count == 1 and pending_count == 0 and last_id:
                    self.redirect(f"/material/{last_id}?msg=" + urllib.parse.quote("采集成功"))
                else:
                    self.redirect("/collect?msg=" + urllib.parse.quote(f"已直接入库 {ok_count} 条，待插件补采 {pending_count} 条。插件会自动打开待补采链接并回填封面和互动数据。"))
                return
            if path in {"/reporting", "/api/import/social-assistant", "/api/import/social_assistant"}:
                return self.api_social_assistant_reporting()
            if path == "/api/extension_collect":
                return self.api_extension_collect()
            if path == "/api/upload_video":
                return self.api_upload_video()
            if path == "/api/upload_wechat_card":
                return self.api_upload_wechat_card()
            if path == "/api/pending_fail":
                return self.api_pending_fail()
            m = re.match(r"^/material/(\d+)/update$", path)
            if m:
                return self.update_material(int(m.group(1)))
            m = re.match(r"^/material/(\d+)/rewrite$", path)
            if m:
                return self.rewrite_material(int(m.group(1)))
            m = re.match(r"^/material/(\d+)/analyze$", path)
            if m:
                return self.analyze_material(int(m.group(1)))
            m = re.match(r"^/material/(\d+)/topic$", path)
            if m:
                return self.add_topic(int(m.group(1)))
            self.send_bytes(b"not found", 404, "text/plain")
        except Exception as e:
            self.send_bytes(page_layout("错误", f"<div class='alert red'>{esc(e)}</div><pre>{esc(traceback.format_exc())}</pre>", ""), 500)

    # ---------- 页面 ----------
    def table_simple(self, rows: list[sqlite3.Row], keys: list[str], names: list[str]) -> str:
        if not rows:
            return '<div class="muted">暂无数据</div>'
        head = "".join(f"<th>{esc(n)}</th>" for n in names)
        body = "".join("<tr>" + "".join(f"<td>{esc(r[k])}</td>" for k in keys) + "</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    def table_materials(self, rows: list[sqlite3.Row]) -> str:
        if not rows:
            return '<div class="muted">暂无数据</div>'
        body = ""
        for r in rows:
            body += f"<tr><td><a href='/material/{r['id']}'><b>{esc(r['title'])}</b></a><br><span class='muted'>{esc(r['platform'])} · {esc(r['author'])}</span></td><td>{esc(r['category'])}</td><td>{fmt_count(r['like_count'])}</td><td>{fmt_count(r['collect_count'])}</td><td>{fmt_count(r['share_count'])}</td></tr>"
        return f"<table><thead><tr><th>标题</th><th>分类</th><th>点赞</th><th>收藏</th><th>转发</th></tr></thead><tbody>{body}</tbody></table>"

    def recommendation(self) -> str:
        with conn() as c:
            cats = c.execute("SELECT category,COUNT(*) n,AVG(like_count) avg_like FROM materials GROUP BY category ORDER BY avg_like DESC,n DESC LIMIT 3").fetchall()
        if not cats:
            return "素材库为空。建议先粘贴 20-50 条同赛道链接，随后用浏览器助手补齐待补采任务，再用 AI 分析高频选题、标题公式和可复刻结构。"
        lines = [f"- 「{r['category']}」素材较多/互动较好，可继续做系列化选题。" for r in cats]
        lines.append("- 建议优先挑选高收藏、高转发素材进入选题库。")
        return "\n".join(lines)

    def index(self) -> None:
        with conn() as c:
            total = c.execute("SELECT COUNT(*) n FROM materials").fetchone()["n"]
            today = c.execute("SELECT COUNT(*) n FROM materials WHERE substr(created_at,1,10)=?", (today_str(),)).fetchone()["n"]
            max_like = c.execute("SELECT MAX(like_count) n FROM materials").fetchone()["n"] or 0
            pending = c.execute("SELECT COUNT(*) n FROM pending_collects WHERE status IN ('待补采','待打开页面','采集中')").fetchone()["n"]
            recent = c.execute("SELECT * FROM materials ORDER BY id DESC LIMIT 6").fetchall()
            top = c.execute("SELECT * FROM materials ORDER BY like_count DESC LIMIT 5").fetchall()
            platform_rows = c.execute("SELECT platform,COUNT(*) n FROM materials GROUP BY platform ORDER BY n DESC").fetchall()
        cards = f"""
<h1>首页概览</h1><div class="sub">严格封面模式：没有封面的素材不会进入素材库。新增：视频号转发卡片导入说明与卡片截图入库。自动任务不再切换当前浏览器页面，手动采集保留最高准确率。</div>
<div class="grid"><div class="stat">已收集视频总数<b>{total}</b></div><div class="stat">今日新增<b>{today}</b></div><div class="stat">最高点赞<b>{fmt_count(max_like)}</b></div><div class="stat">待补采队列<b>{pending}</b></div></div>
<div class="card"><h2>采集提示</h2><div class="alert">现在的流程是：先安装并开启浏览器助手；之后在网站里粘贴抖音/小红书/视频号/快手/B站分享链接，系统会创建待采集任务。浏览器助手会在后台标签页尝试补采，不会切换你当前正在看的页面；如果后台无法拿到封面或疑似采错，会保留在待补采队列，建议再用插件“手动采集当前页面”。</div><a class="btn blue" href="/collect">去采集链接</a> <a class="btn" href="/help">查看插件安装方法</a></div>
<div class="grid2"><div class="card"><h2>热门平台占比</h2>{self.table_simple(platform_rows, ['platform','n'], ['平台','数量'])}</div><div class="card"><h2>AI推荐选题</h2><div class="pre">{esc(self.recommendation())}</div></div></div>
<div class="card"><div class="between"><h2>高赞视频排行</h2><a href="/materials">查看素材库</a></div>{self.table_materials(top)}</div>
<div class="card"><h2>最近采集内容</h2><div class="materials">{''.join(material_card(r) for r in recent) or '<div class="muted">暂无素材，请先采集。</div>'}</div></div>
"""
        self.send_bytes(page_layout("首页概览", cards, "首页概览"))

    def collect_page(self, qs: dict[str, list[str]]) -> None:
        msg = qs.get("msg", [""])[0]
        err = qs.get("err", [""])[0]
        with conn() as c:
            fails = c.execute("SELECT * FROM failed_imports ORDER BY id DESC LIMIT 8").fetchall()
            pendings = c.execute("SELECT * FROM pending_collects WHERE status IN ('待补采','待打开页面','采集中') ORDER BY id DESC LIMIT 12").fetchall()
        fail_html = ""
        if fails:
            rows = []
            for f in fails:
                rows.append(f"<tr><td>{esc(f['platform'])}</td><td>{esc(f['title'] or f['url'])}</td><td>{esc(f['reason'])}</td><td>{esc(f['created_at'])}</td></tr>")
            fail_html = "<div class='card'><h2>最近失败记录</h2><div class='muted'>这些是后台直读失败的尝试，仅作提示。真正的待处理请看下方待补采队列。</div><table><tr><th>平台</th><th>标题/链接</th><th>原因</th><th>时间</th></tr>" + "".join(rows) + "</table></div>"
        pending_html = ""
        if pendings:
            rows = []
            for p in pendings:
                hint = esc(p["last_error"]) if p["last_error"] else '<span class="muted">等待浏览器页面补采</span>'
                rows.append(f"<tr><td>{esc(p['platform'])}</td><td><div><b>{esc(p['title'])}</b></div><div class='muted'>{esc(p['url'])}</div></td><td>{esc(p['status'])}</td><td>{hint}</td><td>{esc(p['updated_at'])}</td></tr>")
            pending_html = "<div class='card'><h2>待补采队列</h2><div class='muted'>你在这里先贴链接。浏览器助手会后台尝试补采；如果失败，打开正确视频详情页后手动采集即可。</div><table><tr><th>平台</th><th>标题/原始链接</th><th>状态</th><th>最近提示</th><th>时间</th></tr>" + "".join(rows) + "</table></div>"
        body = f"""
<h1>链接采集</h1><div class="sub">支持单条链接、整段分享文本、批量导入，也支持把微信聊天框里的视频直接拖入网站。链接走浏览器助手补采；本地视频会自动截取第一帧作为封面入库。</div>
{f'<div class="alert green">{esc(msg)}</div>' if msg else ''}{f'<div class="alert red">{esc(err)}</div>' if err else ''}
<div class="card"><h2>粘贴短视频链接 / 分享文本</h2>
<form method="post" action="/collect"><textarea name="raw" placeholder="每行一个链接，或粘贴完整分享文案：\n3分钟记住 wolf down #英语学习 https://v.douyin.com/xxxx/ 复制此链接打开抖音"></textarea><br><br><button class="btn blue" type="submit">加入采集队列</button> <button class="btn" type="button" onclick="navigator.clipboard.readText().then(t=>document.querySelector('textarea[name=raw]').value=t)">从剪贴板读取</button></form>
</div>


<div class="card"><h2>视频号转发卡片导入</h2>
<div class="alert red"><b>重要说明：</b>微信聊天里的“视频号转发卡片”不是标准网页链接，也不是视频文件。直接从聊天框拖进浏览器时，通常只会给浏览器一个图片/文本预览，里面不包含点赞、评论、收藏、转发等后台数据。卡片本身没有展示的数据，网站无法凭空读取。要拿完整互动数据，仍需要打开对应视频号详情页，让采集助手读取页面上可见的数据，或手动补充。</div>
<div class="sub">这里用于先把微信聊天里的视频号卡片截图/封面入库：可拖入卡片截图、粘贴截图，或手动填写标题/作者/数据。后续再通过“打开原平台页/手动采集”补齐互动数据。</div>
<div id="cardDropZone" style="border:2px dashed #f59e0b;background:#fffbeb;border-radius:18px;padding:28px;text-align:center;cursor:pointer;margin-top:12px">
  <b>拖入视频号卡片截图 / Ctrl+V 粘贴截图 / 点击选择图片</b><br>
  <span class="muted">适合你截图里的微信聊天卡片。图片会作为封面入库；点赞评论等字段需页面补采或手动填写。</span>
  <input id="cardImageFile" type="file" accept="image/*" style="display:none">
</div>
<div class="grid2" style="margin-top:14px">
  <div><label>标题</label><input id="cardTitle" placeholder="例如：张显国家... / 视频号素材标题"></div>
  <div><label>作者</label><input id="cardAuthor" placeholder="视频号作者昵称，可选"></div>
  <div><label>作者主页 / 原平台链接</label><input id="cardSourceUrl" placeholder="有链接就填，没有可留空"></div>
  <div><label>发布时间</label><input id="cardPublishTime" placeholder="例如：2天前 / 2026-04-24"></div>
</div>
<div class="grid" style="margin-top:8px">
  <div><label>点赞</label><input id="cardLike" placeholder="可选"></div>
  <div><label>评论</label><input id="cardComment" placeholder="可选"></div>
  <div><label>收藏</label><input id="cardCollect" placeholder="可选"></div>
  <div><label>转发</label><input id="cardShare" placeholder="可选"></div>
</div>
<label>文案 / 备注</label><textarea id="cardCaption" placeholder="可粘贴视频号文案、聊天备注、后续改写素材"></textarea>
<label>标签，逗号分隔</label><input id="cardTags" placeholder="视频号,微信转发,待补采">
<div id="cardPreview" style="margin-top:14px"></div>
<div class="row" style="margin-top:14px"><button class="btn orange" type="button" id="cardUploadBtn">用卡片截图入库</button><span id="cardStatus" class="muted"></span></div>
<script>
(function(){{
  const dz = document.getElementById('cardDropZone');
  const input = document.getElementById('cardImageFile');
  const preview = document.getElementById('cardPreview');
  const status = document.getElementById('cardStatus');
  const btn = document.getElementById('cardUploadBtn');
  let cardCover = '';
  function setStatus(t, cls) {{ status.className = cls || 'muted'; status.textContent = t || ''; }}
  function esc(s) {{ return String(s || '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
  function isImage(f) {{ return f && ((f.type || '').startsWith('image/') || /\.(png|jpg|jpeg|webp|gif)$/i.test(f.name || '')); }}
  function firstImage(dt) {{
    if (!dt) return null;
    if (dt.files && dt.files.length) {{ for (const f of dt.files) if (isImage(f)) return f; }}
    if (dt.items && dt.items.length) {{ for (const it of dt.items) if (it.kind === 'file') {{ const f = it.getAsFile(); if (isImage(f)) return f; }} }}
    return null;
  }}
  function pickImage(file) {{
    if (!file) return setStatus('没有读取到图片。微信卡片如果拖不出来，请先截图，然后在本页 Ctrl+V 粘贴截图。', 'danger');
    if (!isImage(file)) return setStatus('读取到的不是图片文件。视频号卡片通常建议截图后导入。', 'danger');
    const reader = new FileReader();
    reader.onload = () => {{
      cardCover = String(reader.result || '');
      preview.innerHTML = '<div class="grid2"><div><img class="detail-cover" style="max-height:260px" src="'+cardCover+'"></div><div class="pre">卡片截图已读取。\n说明：这张图会作为素材封面。\n互动数据不会从聊天卡片自动获得，需要打开视频号详情页补采或手动填写。</div></div>';
      setStatus('卡片截图已读取，可以入库。', 'ok');
    }};
    reader.onerror = () => setStatus('图片读取失败。', 'danger');
    reader.readAsDataURL(file);
  }}
  dz.addEventListener('click', () => input.click());
  input.addEventListener('change', e => pickImage(e.target.files[0]));
  dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.style.background='#fef3c7'; }});
  dz.addEventListener('dragleave', e => {{ dz.style.background='#fffbeb'; }});
  dz.addEventListener('drop', e => {{
    e.preventDefault(); e.stopPropagation(); dz.style.background='#fffbeb';
    const img = firstImage(e.dataTransfer);
    if (img) return pickImage(img);
    const text = e.dataTransfer.getData('text/plain') || e.dataTransfer.getData('text/uri-list') || '';
    if (text) {{
      const ta = document.querySelector('textarea[name=raw]');
      if (ta) ta.value = text;
      setStatus('拖入的是文本/链接，不是卡片截图。已放入上方链接采集框，请点击“加入采集队列”。', 'warn');
    }} else {{
      setStatus('微信没有向浏览器释放卡片图片或链接。请对视频号卡片截图后 Ctrl+V 粘贴到这里。', 'danger');
    }}
  }});
  document.addEventListener('paste', e => {{
    const img = firstImage(e.clipboardData);
    if (img) {{ e.preventDefault(); pickImage(img); }}
  }});
  btn.addEventListener('click', async () => {{
    if (!cardCover) return setStatus('请先拖入或粘贴一张视频号卡片截图。', 'danger');
    const title = document.getElementById('cardTitle').value.trim() || '微信视频号转发卡片素材';
    const payload = {{
      cover_data: cardCover,
      title,
      author: document.getElementById('cardAuthor').value,
      source_url: document.getElementById('cardSourceUrl').value,
      publish_time: document.getElementById('cardPublishTime').value,
      like_count: document.getElementById('cardLike').value,
      comment_count: document.getElementById('cardComment').value,
      collect_count: document.getElementById('cardCollect').value,
      share_count: document.getElementById('cardShare').value,
      caption: document.getElementById('cardCaption').value,
      tags: document.getElementById('cardTags').value || '视频号,微信转发,卡片截图,待补采'
    }};
    setStatus('正在入库...', 'warn');
    try {{
      const res = await fetch('/api/upload_wechat_card', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || '入库失败');
      setStatus(data.message || '入库成功', 'ok');
      setTimeout(() => location.href = data.url, 600);
    }} catch(e) {{ setStatus(e.message, 'danger'); }}
  }});
}})();
</script>
</div>

<div class="card"><h2>微信 / 本地视频上传</h2>
<div class="sub">说明：微信聊天窗口里的“视频卡片”有时不能被浏览器直接识别成文件。新版支持三种方式：①拖入真正的视频文件；②点击选择本地视频；③先在微信里复制/另存视频文件，再回到本页面按 Ctrl+V 粘贴。系统会保存视频，并自动截取第一帧作为封面。</div>
<div id="dropZone" style="border:2px dashed #93c5fd;background:#eff6ff;border-radius:18px;padding:30px;text-align:center;cursor:pointer">
  <b>把视频文件拖到这里 / 点击选择视频 / Ctrl+V 粘贴视频文件</b><br>
  <span class="muted">支持 MP4 / MOV / M4V / WebM / AVI / MKV。微信聊天卡片如果拖不进来，请先在微信里“另存为”或“打开文件位置”后再拖入。</span>
  <input id="videoFile" type="file" accept="video/*,.mp4,.mov,.m4v,.webm,.avi,.mkv" style="display:none">
</div>
<div class="alert" style="margin-top:12px">如果你从微信聊天框直接拖拽后没有反应，说明微信没有把该视频释放成标准文件对象，浏览器无法读取。请先在微信中点击下载视频，右键视频选择“另存为/打开文件夹”，再把保存后的 MP4 拖进来；或者复制该视频文件后在本页按 Ctrl+V。</div>
<div class="grid2" style="margin-top:14px">
  <div><label>素材标题，可自动用文件名</label><input id="uploadTitle" placeholder="例如：微信分享视频素材 / 英语口播素材"></div>
  <div><label>补充文案，可选</label><input id="uploadNote" placeholder="可以填写视频文案、备注或来源说明"></div>
</div>
<div id="uploadPreview" style="margin-top:14px"></div>
<div class="row" style="margin-top:14px"><button class="btn green" type="button" id="uploadBtn">上传并自动截取第一帧封面</button><span id="uploadStatus" class="muted"></span></div>
<script>
(function(){{
  const dz = document.getElementById('dropZone');
  const fileInput = document.getElementById('videoFile');
  const btn = document.getElementById('uploadBtn');
  const status = document.getElementById('uploadStatus');
  const preview = document.getElementById('uploadPreview');
  let currentFile = null;
  let coverData = '';
  let meta = {{}};

  function setStatus(txt, cls) {{
    status.className = cls || 'muted';
    status.textContent = txt || '';
  }}

  function seconds(v) {{
    if (!isFinite(v) || v <= 0) return '';
    return Math.round(v * 10) / 10;
  }}

  function isVideoFile(file) {{
    if (!file) return false;
    const name = (file.name || '').toLowerCase();
    return (file.type && file.type.startsWith('video/')) || /\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(name);
  }}

  function escapeHtml(s) {{
    return String(s || '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  }}

  function extractFileFromTransfer(dt) {{
    if (!dt) return null;
    if (dt.files && dt.files.length) {{
      for (const f of dt.files) if (isVideoFile(f)) return f;
      return dt.files[0];
    }}
    if (dt.items && dt.items.length) {{
      for (const item of dt.items) {{
        if (item.kind === 'file') {{
          const f = item.getAsFile();
          if (isVideoFile(f)) return f;
        }}
      }}
    }}
    return null;
  }}

  function pickFile(file) {{
    if (!file) {{
      setStatus('没有读取到视频文件。微信聊天卡片可能不是标准文件拖拽，请先另存为/打开文件位置后再拖入，或点击选择本地视频。', 'danger');
      return;
    }}
    if (!isVideoFile(file)) {{
      setStatus('读取到的不是视频文件：' + (file.name || file.type || '未知文件'), 'danger');
      return;
    }}
    currentFile = file;
    coverData = '';
    meta = {{}};
    setStatus('正在读取视频并截取第一帧...', 'warn');
    preview.innerHTML = '<div class="alert">正在解析视频：'+escapeHtml(file.name || '未命名视频')+'</div>';
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.playsInline = true;
    video.src = url;
    let captured = false;

    video.onloadedmetadata = function() {{
      meta.duration = seconds(video.duration);
      meta.width = video.videoWidth || '';
      meta.height = video.videoHeight || '';
      try {{
        const seekTo = Math.min(0.5, Math.max(0, (video.duration || 1) / 20));
        video.currentTime = seekTo;
      }} catch(e) {{
        capture();
      }}
    }};
    video.onloadeddata = function() {{
      if (!captured && (!video.duration || video.duration < 0.2)) capture();
    }};
    video.onseeked = capture;
    video.onerror = function() {{
      URL.revokeObjectURL(url);
      setStatus('视频读取失败。微信里的部分视频可能是特殊编码，建议另存为 MP4/H.264 后再上传。', 'danger');
    }};
    setTimeout(() => {{ if (!captured && video.readyState >= 2) capture(); }}, 2000);

    function capture() {{
      if (captured) return;
      captured = true;
      try {{
        const canvas = document.createElement('canvas');
        const w = video.videoWidth || 720;
        const h = video.videoHeight || 1280;
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, w, h);
        coverData = canvas.toDataURL('image/jpeg', 0.88);
        URL.revokeObjectURL(url);
        preview.innerHTML = '<div class="grid2"><div><img class="detail-cover" style="max-height:260px" src="'+coverData+'"></div><div class="pre">文件名：'+escapeHtml(file.name || '未命名视频')+'\n文件大小：'+(file.size/1024/1024).toFixed(2)+' MB\n视频时长：'+(meta.duration || '未读取')+' 秒\n分辨率：'+(meta.width&&meta.height ? meta.width+'×'+meta.height : '未读取')+'\n封面：已截取第一帧</div></div>';
        setStatus('第一帧封面已生成，可以上传入库。', 'ok');
      }} catch(e) {{
        URL.revokeObjectURL(url);
        setStatus('第一帧封面生成失败：' + e.message + '。建议把视频转成 MP4/H.264。', 'danger');
      }}
    }}
  }}

  dz.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', e => pickFile(e.target.files[0]));

  function handleDrop(e) {{
    e.preventDefault();
    e.stopPropagation();
    dz.style.background='#eff6ff';
    const file = extractFileFromTransfer(e.dataTransfer);
    if (file) return pickFile(file);
    const text = e.dataTransfer.getData('text/plain') || e.dataTransfer.getData('text/uri-list') || '';
    if (text) {{
      setStatus('拖进来的不是视频文件，而是文本/链接。已识别到：' + text.slice(0, 80) + '。如果这是抖音/小红书链接，请粘贴到上面的链接采集框；如果是微信视频，请先另存为文件再拖入。', 'danger');
    }} else {{
      setStatus('浏览器没有从这次拖拽中收到视频文件。请先在微信中下载/另存为视频，再从文件夹拖入。', 'danger');
    }}
  }}

  dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.style.background='#dbeafe'; }});
  dz.addEventListener('dragleave', e => {{ dz.style.background='#eff6ff'; }});
  dz.addEventListener('drop', handleDrop);

  document.addEventListener('dragover', e => {{
    if (e.dataTransfer) e.preventDefault();
  }});
  document.addEventListener('drop', e => {{
    if (e.target && dz.contains(e.target)) return;
    if (e.dataTransfer && (e.dataTransfer.files.length || e.dataTransfer.items.length)) handleDrop(e);
  }});

  document.addEventListener('paste', e => {{
    const file = extractFileFromTransfer(e.clipboardData);
    if (file) {{
      e.preventDefault();
      pickFile(file);
    }}
  }});

  btn.addEventListener('click', async () => {{
    if (!currentFile) return setStatus('请先拖入、粘贴或选择一个视频文件。', 'danger');
    if (!coverData) return setStatus('第一帧封面还没生成，请稍等。', 'danger');
    const form = new FormData();
    form.append('video', currentFile, currentFile.name || 'wechat_video.mp4');
    form.append('cover_data', coverData);
    form.append('title', document.getElementById('uploadTitle').value || (currentFile.name || '微信视频素材').replace(/\.[^.]+$/, ''));
    form.append('note', document.getElementById('uploadNote').value || '微信/本地视频拖拽上传');
    form.append('duration', meta.duration || '');
    form.append('width', meta.width || '');
    form.append('height', meta.height || '');
    setStatus('正在上传并入库...', 'warn');
    try {{
      const res = await fetch('/api/upload_video', {{ method:'POST', body:form }});
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || '上传失败');
      setStatus(data.message || '上传成功', 'ok');
      setTimeout(() => {{ location.href = data.url; }}, 600);
    }} catch(e) {{
      setStatus(e.message, 'danger');
    }}
  }});
}})();
</script>
</div>

<div class="card"><h2>新的工作流</h2><div class="pre">1. 先把短视频链接粘贴到这里，系统会立即生成待补采任务。\n2. 如果平台公开页能直接读到封面和标题，会立即入库。\n3. 如果读不到完整封面/互动数据，这条任务会保留在待补采队列。\n4. 浏览器助手会在后台标签页尝试读取页面可见信息，不会切换你当前页面。
5. Chrome 无法给后台隐藏标签页截图；如果后台没有拿到封面，任务会继续留在待补采队列。
6. 这时打开正确视频详情页，点击插件“手动采集当前页面”，系统会用当前页面截图当封面并入库。\n7. 回传成功后，素材自动进入正式素材库。\n8. 如果是微信聊天里的视频文件，可以直接拖到上方上传区，系统会保存视频文件并截取第一帧作为封面。</div><a class="btn green" href="/help">安装 / 开启浏览器采集助手</a></div>
{pending_html}
{fail_html}
"""
        self.send_bytes(page_layout("链接采集", body, "链接采集"))

    def materials(self, qs: dict[str, list[str]]) -> None:
        kw = qs.get("kw", [""])[0].strip()
        platform = qs.get("platform", [""])[0]
        category = qs.get("category", [""])[0]
        status = qs.get("status", [""])[0]
        min_like = parse_int(qs.get("min_like", [""])[0])
        where = []
        args: list[Any] = []
        if kw:
            where.append("(title LIKE ? OR description LIKE ? OR transcript LIKE ? OR tags LIKE ? OR author LIKE ? OR url LIKE ?)")
            args += [f"%{kw}%"] * 6
        if platform:
            where.append("platform=?")
            args.append(platform)
        if category:
            where.append("category=?")
            args.append(category)
        if status:
            where.append("status=?")
            args.append(status)
        if min_like:
            where.append("like_count>=?")
            args.append(min_like)
        sql = "SELECT * FROM materials" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC"
        with conn() as c:
            rows = c.execute(sql, args).fetchall()
        opt_platform = "<option value=''>全部平台</option>" + "".join(f"<option {'selected' if platform==p else ''}>{p}</option>" for p in PLATFORMS)
        opt_cat = "<option value=''>全部分类</option>" + "".join(f"<option {'selected' if category==p else ''}>{p}</option>" for p in CATEGORIES)
        opt_status = "<option value=''>全部状态</option>" + "".join(f"<option {'selected' if status==p else ''}>{p}</option>" for p in STATUSES)
        body = f"""
<h1>素材库</h1><div class="sub">展示已成功采集并有封面的素材。当前 {len(rows)} 条。</div>
<div class="card"><form method="get" action="/materials"><div class="grid"><div><label>关键词</label><input name="kw" value="{esc(kw)}" placeholder="标题 / 文案 / 标签 / 作者 / 链接"></div><div><label>平台</label><select name="platform">{opt_platform}</select></div><div><label>分类</label><select name="category">{opt_cat}</select></div><div><label>状态</label><select name="status">{opt_status}</select></div></div><div class="row" style="margin-top:14px"><input style="max-width:300px" name="min_like" value="{esc(min_like if min_like else '')}" placeholder="点赞数大于，例如 10000"><button class="btn blue">筛选</button><a class="btn" href="/materials">清空</a><a class="btn green" href="/collect">添加素材链接</a></div></form></div>
<div class="card"><div class="between"><h2>素材列表</h2><b class="ok">{len(rows)} 条</b></div><div class="materials">{''.join(material_card(r) for r in rows) or '<div class="muted">暂无素材。请先在“链接采集”页面添加。</div>'}</div></div>
"""
        self.send_bytes(page_layout("素材库", body, "素材库"))

    def material_detail(self, mid: int, qs: dict[str, list[str]]) -> None:
        with conn() as c:
            r = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
        if not r:
            self.send_bytes(page_layout("未找到", "<h1>素材不存在</h1>", "素材库"), 404)
            return
        msg = qs.get("msg", [""])[0]
        cover = f'<img class="detail-cover" src="{esc(r["cover_url"])}" alt="封面">'
        video = f'<video controls src="{esc(r["video_file_url"])}" style="width:100%;border-radius:18px"></video>' if r["video_file_url"] else '<div class="alert">未采集到可站内播放的视频文件直链。平台链接只能打开原平台页；如需站内播放，请在下方填写 MP4 视频文件直链。</div>'
        platform_opts = "".join([f'<option {'selected' if r["platform"]==p else ''}>{p}</option>' for p in PLATFORMS])
        cat_opts = "".join([f'<option {'selected' if r["category"]==p else ''}>{p}</option>' for p in CATEGORIES])
        status_opts = "".join([f'<option {'selected' if r["status"]==p else ''}>{p}</option>' for p in STATUSES])
        body = f"""
<h1>素材详情 / AI</h1><div class="sub">{esc(r['platform'])} · {esc(r['category'])} · {esc(r['status'])}</div>{f'<div class="alert green">{esc(msg)}</div>' if msg else ''}
<div class="grid2"><div class="card"><h2>{esc(r['title'])}</h2>{cover}<div class="row" style="margin-top:14px"><a class="btn" href="{esc(r['url'])}" target="_blank">打开原平台页</a>{f'<a class="btn" href="{esc(r['author_url'])}" target="_blank">打开作者主页</a>' if r['author_url'] else ''}</div></div>
<div class="card"><h2>直接数据</h2><table><tr><th>作者</th><td>{esc(r['author'] or '未填写')}</td></tr><tr><th>发布时间</th><td>{esc(r['publish_time'] or '未填写')}</td></tr><tr><th>点赞</th><td>{fmt_count(r['like_count'])}</td></tr><tr><th>评论</th><td>{fmt_count(r['comment_count'])}</td></tr><tr><th>收藏</th><td>{fmt_count(r['collect_count'])}</td></tr><tr><th>转发</th><td>{fmt_count(r['share_count'])}</td></tr><tr><th>播放</th><td>{fmt_count(r['play_count'])}</td></tr><tr><th>来源方式</th><td>{esc(r['source_method'])}</td></tr></table>{video}</div></div>
<div class="grid2"><div class="card"><h2>视频原文案 / 自动提取文案</h2><div class="pre">{esc(r['transcript'] or r['description'] or '暂无文案。可手动补充，或用浏览器采集助手读取当前页面可见文案。')}</div></div><div class="card"><h2>AI总结</h2><div class="pre">{esc(r['ai_summary'])}</div></div></div>
<div class="grid2"><div class="card"><h2>AI爆款分析</h2><div class="pre">{esc(r['ai_analysis'] or '尚未分析，点击下方按钮生成。')}</div><form method="post" action="/material/{mid}/analyze"><button class="btn blue">生成 / 更新分析</button></form></div><div class="card"><h2>AI文案改写</h2><div class="pre">{esc(r['rewritten_copy'] or '尚未改写，选择方向后生成。')}</div><form method="post" action="/material/{mid}/rewrite"><select name="style"><option>抖音爆款版</option><option>小红书种草版</option><option>视频号知识版</option><option>口播脚本版</option><option>分镜脚本版</option><option>卖课引流版</option><option>评论区互动版</option></select><br><br><button class="btn blue">生成改写</button></form></div></div>
<div class="card"><h2>编辑素材</h2><form method="post" action="/material/{mid}/update"><div class="grid2"><div><label>标题</label><input name="title" value="{esc(r['title'])}"></div><div><label>封面图片 URL / 本地封面路径</label><input name="cover_url" value="{esc(r['cover_url'])}" required></div><div><label>作者昵称</label><input name="author" value="{esc(r['author'])}"></div><div><label>作者主页链接</label><input name="author_url" value="{esc(r['author_url'])}"></div><div><label>视频文件直链 MP4，可选</label><input name="video_file_url" value="{esc(r['video_file_url'])}"></div><div><label>发布时间</label><input name="publish_time" value="{esc(r['publish_time'])}"></div><div><label>平台</label><select name="platform">{platform_opts}</select></div><div><label>分类</label><select name="category">{cat_opts}</select></div><div><label>状态</label><select name="status">{status_opts}</select></div><div><label>项目文件夹</label><input name="project" value="{esc(r['project'])}"></div></div><div class="grid"><div><label>点赞</label><input name="like_count" value="{esc(r['like_count'])}"></div><div><label>评论</label><input name="comment_count" value="{esc(r['comment_count'])}"></div><div><label>收藏</label><input name="collect_count" value="{esc(r['collect_count'])}"></div><div><label>转发</label><input name="share_count" value="{esc(r['share_count'])}"></div></div><label>标签，逗号分隔</label><input name="tags" value="{esc(r['tags'])}"><label>原文案 / 口播稿</label><textarea name="transcript">{esc(r['transcript'])}</textarea><br><br><button class="btn green">保存编辑</button></form></div>
<div class="card"><h2>加入选题库</h2><form method="post" action="/material/{mid}/topic"><button class="btn blue">一键加入选题库</button></form></div>
"""
        self.send_bytes(page_layout("素材详情", body, "素材库"))

    # ---------- 行为 ----------
    def update_material(self, mid: int) -> None:
        f = self.form()
        fields = ["title", "cover_url", "author", "author_url", "video_file_url", "publish_time", "platform", "category", "status", "project", "like_count", "comment_count", "collect_count", "share_count", "tags", "transcript"]
        vals: list[Any] = []
        if not f.get("cover_url"):
            self.redirect(f"/material/{mid}?msg=" + urllib.parse.quote("保存失败：封面不能为空"))
            return
        for k in fields:
            v = f.get(k, "")
            if k.endswith("_count"):
                v = parse_int(v)
            vals.append(v)
        vals.append(heat_level(parse_int(f.get("like_count")), parse_int(f.get("collect_count")), parse_int(f.get("share_count"))))
        vals += [now_str(), mid]
        with conn() as c:
            c.execute(
                "UPDATE materials SET title=?,cover_url=?,author=?,author_url=?,video_file_url=?,publish_time=?,platform=?,category=?,status=?,project=?,like_count=?,comment_count=?,collect_count=?,share_count=?,tags=?,transcript=?,heat_level=?,updated_at=? WHERE id=?",
                vals,
            )
            c.commit()
        self.redirect(f"/material/{mid}?msg=" + urllib.parse.quote("已保存"))

    def rewrite_material(self, mid: int) -> None:
        f = self.form()
        with conn() as c:
            r = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
            if not r:
                self.redirect("/materials")
                return
            txt = ai_rewrite(r, f.get("style", ""))
            c.execute("UPDATE materials SET rewritten_copy=?,status=?,updated_at=? WHERE id=?", (txt, "已改写", now_str(), mid))
            c.commit()
        self.redirect(f"/material/{mid}?msg=" + urllib.parse.quote("AI改写已生成"))

    def analyze_material(self, mid: int) -> None:
        with conn() as c:
            r = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
            if not r:
                self.redirect("/materials")
                return
            txt = ai_analyze(r)
            c.execute("UPDATE materials SET ai_analysis=?,status=?,updated_at=? WHERE id=?", (txt, "已分析", now_str(), mid))
            c.commit()
        self.redirect(f"/material/{mid}?msg=" + urllib.parse.quote("AI分析已生成"))

    def add_topic(self, mid: int) -> None:
        with conn() as c:
            r = c.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
            if not r:
                self.redirect("/materials")
                return
            c.execute(
                "INSERT INTO topics(title,material_id,reference_author,rewritten_copy,shot_form,storyboard,status,publish_platform,final_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (r["title"], mid, r["author"], r["rewritten_copy"] or "", "待定", "", "待制作", r["platform"], "", now_str(), now_str()),
            )
            c.execute("UPDATE materials SET status=?,updated_at=? WHERE id=?", ("已加入选题", now_str(), mid))
            c.commit()
        self.redirect("/topics?msg=" + urllib.parse.quote("已加入选题库"))

    # ---------- API ----------
    def api_social_assistant_reporting(self) -> None:
        """接收社媒助手「数据上报」payload。
        V6.9 修复点：
        1. 记录每一次上报日志，方便判断到底有没有打到本站。
        2. 兼容 JSON / form-urlencoded / list/data/items/records 等多种结构。
        3. 如果全部失败，返回 422，让社媒助手不要误判为“成功”。
        """
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_bytes = self.rfile.read(length)
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        body = parse_reporting_body(raw_text, self.headers.get("Content-Type", ""))
        try:
            items, meta, extra = find_reporting_items(body)
            if not items:
                msg = "没有在上报内容中找到素材数据 list/items/records。请确认社媒助手点的是采集结果页的『数据上报』，并已勾选自定义上报字段。"
                record_reporting_log("failed", msg, raw_text, body, 0, 0)
                self.send_bytes(json.dumps({"ok": False, "message": msg}, ensure_ascii=False).encode("utf-8"), status=400, content_type="application/json; charset=utf-8")
                return
            aliases = build_aliases_from_meta(meta)
            ok_ids: list[int] = []
            failed: list[dict[str, str]] = []
            for item in items:
                try:
                    data = normalize_social_assistant_item(item, aliases, extra)
                    if not data.get("cover_url"):
                        raise ValueError("上报数据中没有封面字段。请在社媒助手『自定义上报字段』里勾选：封面图/封面图链接/note_cover。")
                    mid = save_material(data)
                    ok_ids.append(mid)
                except Exception as e:
                    raw_item = json.dumps(item, ensure_ascii=False)
                    record_failed({
                        "url": as_text(item.get("url") or item.get("video_url") or item.get("note_url") or item.get("作品链接") or item.get("视频链接")),
                        "platform": as_text(item.get("platform") or item.get("平台")) or "社媒助手",
                        "title": as_text(item.get("title") or item.get("content") or item.get("标题") or item.get("内容"))[:180],
                        "raw_copy": raw_item
                    }, str(e), raw_item)
                    failed.append({"title": as_text(item.get("title") or item.get("content") or item.get("标题") or item.get("内容"))[:80], "reason": str(e)})
            if ok_ids:
                msg = f"已接收社媒助手上报：成功入库 {len(ok_ids)} 条，失败 {len(failed)} 条"
                record_reporting_log("success" if not failed else "partial", msg, raw_text, {"meta": meta, "items_count": len(items), "failed": failed[:5]}, len(ok_ids), len(failed))
                payload = {"ok": True, "message": msg, "inserted": len(ok_ids), "failed": len(failed), "ids": ok_ids[:50], "failed_items": failed[:20]}
                self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")
                return
            msg = "社媒助手已请求本站，但没有素材成功入库。请到本站『数据上报』页面查看失败原因；常见原因是没有勾选封面字段。"
            record_reporting_log("failed", msg, raw_text, {"meta": meta, "items_count": len(items), "failed": failed[:20]}, 0, len(failed))
            payload = {"ok": False, "message": msg, "inserted": 0, "failed": len(failed), "failed_items": failed[:20]}
            self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), status=422, content_type="application/json; charset=utf-8")
        except Exception as e:
            msg = str(e)
            record_reporting_log("error", msg, raw_text, body, 0, 0)
            self.send_bytes(json.dumps({"ok": False, "message": msg}, ensure_ascii=False).encode("utf-8"), status=500, content_type="application/json; charset=utf-8")

    def api_pending_match(self, qs: dict[str, list[str]]) -> None:
        url = qs.get("url", [""])[0]
        platform = qs.get("platform", [""])[0] or detect_platform(url, "")
        title = qs.get("title", [""])[0]
        row = match_pending_collect(url, platform, title)
        payload = {
            "ok": True,
            "match": bool(row),
            "pending_id": int(row["id"]) if row else None,
            "platform": row["platform"] if row else platform,
            "title": row["title"] if row else "",
            "status": row["status"] if row else "",
        }
        if row:
            update_pending_collect(int(row["id"]), "采集中", row["last_error"] or "")
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")

    def api_pending_next(self) -> None:
        row = get_next_pending_collect()
        if not row:
            payload = {"ok": True, "task": None}
        else:
            payload = {
                "ok": True,
                "task": {
                    "id": int(row["id"]),
                    "url": row["url"],
                    "normalized_url": row["normalized_url"],
                    "platform": row["platform"],
                    "title": row["title"],
                    "raw_input": row["raw_input"],
                    "content_key": row["content_key"],
                },
            }
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")

    def api_pending_fail(self) -> None:
        body = self.json_body()
        pid = int(body.get("pending_id") or 0)
        msg = str(body.get("message") or "自动采集失败")[:500]
        if pid:
            update_pending_collect(pid, "待补采", msg)
        self.send_bytes(json.dumps({"ok": True, "message": "已记录失败原因"}, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")


    def api_upload_wechat_card(self) -> None:
        """微信视频号转发卡片截图/图片入库。说明：聊天卡片本身不包含互动数据，字段由用户填写或后续补采。"""
        try:
            body = self.json_body()
            title = str(body.get("title") or "微信视频号转发卡片素材").strip()[:180]
            cover_data = body.get("cover_data") or ""
            cover_url = save_cover_data_url(cover_data)
            if not cover_url:
                raise ValueError("没有收到有效的卡片截图/封面图片。请先截图或粘贴图片。")
            source_url = str(body.get("source_url") or "").strip()
            if not source_url:
                digest = hashlib.sha1((title + cover_url + str(time.time())).encode("utf-8")).hexdigest()[:16]
                source_url = f"wechat_channels_card://{digest}"
            caption = str(body.get("caption") or "").strip()
            tags = str(body.get("tags") or "视频号,微信转发,卡片截图,待补采").strip()
            description = caption or "从微信聊天中的视频号转发卡片截图导入。互动数据需要打开视频号详情页补采，或手动填写。"
            data = {
                "url": source_url,
                "platform": "视频号",
                "title": title,
                "author": str(body.get("author") or "未填写").strip(),
                "author_url": source_url if source_url.startswith("http") else "",
                "cover_url": cover_url,
                "video_file_url": "",
                "description": description,
                "raw_copy": description,
                "transcript": caption,
                "like_count": parse_int(body.get("like_count")),
                "comment_count": parse_int(body.get("comment_count")),
                "collect_count": parse_int(body.get("collect_count")),
                "share_count": parse_int(body.get("share_count")),
                "play_count": 0,
                "publish_time": str(body.get("publish_time") or "").strip(),
                "tags": tags,
                "category": classify(title, caption, tags),
                "status": "待处理" if not any([body.get("like_count"), body.get("comment_count"), body.get("collect_count"), body.get("share_count")]) else "已分类",
                "source_method": "wechat_channels_card_screenshot_import",
            }
            mid = save_material(data)
            self.send_bytes(json.dumps({"ok": True, "id": mid, "url": f"/material/{mid}", "message": "视频号卡片已入库。注意：聊天卡片不含点赞评论等数据，如需完整数据请打开详情页补采。"}, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")
        except Exception as e:
            self.send_bytes(json.dumps({"ok": False, "message": str(e)}, ensure_ascii=False).encode("utf-8"), status=400, content_type="application/json; charset=utf-8")

    def api_upload_video(self) -> None:
        """用户从微信聊天框/本地文件夹拖入视频：保存视频文件，并使用前端截取的第一帧作为封面。"""
        try:
            fields, files = self.multipart_form()
            item = files.get("video")
            if not item:
                raise ValueError("没有收到视频文件。请把微信里的视频拖到上传区域，或点击选择本地视频。")
            raw_video = item.get("data") or b""
            filename = safe_filename(str(item.get("filename") or "uploaded_video.mp4"))
            title = (fields.get("title") or Path(filename).stem or "本地视频素材").strip()[:160]
            cover_data = fields.get("cover_data") or ""
            cover_url = save_cover_data_url(cover_data)
            if not cover_url:
                raise ValueError("没有生成第一帧封面。请确认视频能在浏览器中播放，或换成 MP4/H.264 格式后再拖入。")
            video_url = save_video_bytes(filename, raw_video)
            size_mb = len(raw_video) / 1024 / 1024
            duration = fields.get("duration") or ""
            width = fields.get("width") or ""
            height = fields.get("height") or ""
            resolution = f"{width}×{height}" if width and height else "未读取"
            note = (fields.get("note") or "").strip()
            info = f"本地拖入视频文件：{filename}\n文件大小：{size_mb:.2f} MB\n视频时长：{duration or '未读取'} 秒\n视频分辨率：{resolution}"
            if note:
                info += "\n补充说明：" + note
            data = {
                "url": video_url,
                "platform": "微信视频",
                "title": title,
                "author": "本地上传",
                "author_url": "",
                "cover_url": cover_url,
                "video_file_url": video_url,
                "description": info,
                "raw_copy": info,
                "transcript": note or info,
                "like_count": 0,
                "comment_count": 0,
                "collect_count": 0,
                "share_count": 0,
                "play_count": 0,
                "publish_time": now_str(),
                "tags": "微信拖入,本地视频,第一帧封面",
                "category": classify(title, note, "微信拖入,本地视频"),
                "source_method": "local_video_drag_upload",
            }
            mid = save_material(data)
            self.send_bytes(json.dumps({"ok": True, "id": mid, "url": f"/material/{mid}", "message": "视频已入库，已截取第一帧作为封面"}, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")
        except Exception as e:
            self.send_bytes(json.dumps({"ok": False, "message": str(e)}, ensure_ascii=False).encode("utf-8"), status=400, content_type="application/json; charset=utf-8")

    def api_extension_collect(self) -> None:
        body = self.json_body()
        pending_id = int(body.get("pending_id") or 0)
        pending = None
        if pending_id:
            with conn() as c:
                pending = c.execute("SELECT * FROM pending_collects WHERE id=?", (pending_id,)).fetchone()
        cover_url = body.get("cover_url") or ""
        screenshot = body.get("screenshot") or ""
        if screenshot:
            saved = save_cover_data_url(screenshot)
            if saved:
                cover_url = saved
        elif cover_url.startswith("data:image/"):
            cover_url = save_cover_data_url(cover_url)
        raw = body.get("raw_copy") or body.get("text") or body.get("title") or ""
        url = body.get("url") or (pending["url"] if pending else "")
        pending_title = (pending["title"] if pending else "") or ""
        pending_raw = (pending["raw_input"] if pending else "") or ""
        title = body.get("title") or ""
        if (not title) or title in {"抖音", "抖音精选", "抖音-记录美好生活", "小红书"} or len(title) < 4:
            title = pending_title or clean_share_title(pending_raw) or "未命名素材"
        transcript = body.get("transcript") or body.get("description") or ""
        if (not transcript or len(transcript) < 8) and pending_raw:
            transcript = clean_share_title(pending_raw)
        data = {
            "url": url,
            "platform": body.get("platform") or (pending["platform"] if pending else "") or detect_platform(url, raw),
            "title": title,
            "author": body.get("author") or "",
            "author_url": body.get("author_url") or "",
            "cover_url": cover_url,
            "video_file_url": body.get("video_file_url") or "",
            "description": body.get("description") or transcript,
            "raw_copy": pending_raw or raw,
            "transcript": transcript or pending_raw or raw,
            "like_count": parse_int(body.get("like_count")),
            "comment_count": parse_int(body.get("comment_count")),
            "collect_count": parse_int(body.get("collect_count")),
            "share_count": parse_int(body.get("share_count")),
            "play_count": parse_int(body.get("play_count")),
            "publish_time": body.get("publish_time") or "",
            "tags": ",".join(body.get("tags", [])) if isinstance(body.get("tags"), list) else body.get("tags", ""),
            "source_method": "browser_extension_background" if body.get("capture_mode") == "background" else ("browser_extension_one_step" if body.get("capture_mode") in {"one_step", "auto_open"} else ("browser_extension_auto" if body.get("capture_mode") == "auto" else "browser_extension")),
        }
        try:
            # 后台自动采集必须做内容一致性校验。手动采集不拦截，因为用户已确认当前页面。
            capture_mode = body.get("capture_mode") or ""
            if pending and capture_mode != "manual":
                ok_match, match_msg = auto_capture_matches_pending(pending_raw, pending_title, data["title"], data["transcript"])
                if not ok_match:
                    raise ValueError(match_msg)
            mid = save_material(data)
            if pending_id:
                update_pending_collect(pending_id, "已完成", "", mid)
            else:
                row = match_pending_collect(url, data["platform"], data["title"])
                if row:
                    update_pending_collect(int(row["id"]), "已完成", "", mid)
            self.send_bytes(json.dumps({"ok": True, "id": mid, "url": f"http://{HOST}:{PORT}/material/{mid}", "message": "采集成功，已入库并生成封面"}, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")
        except Exception as e:
            if pending_id:
                update_pending_collect(pending_id, "待补采", str(e))
            record_failed(data, str(e), raw)
            self.send_bytes(json.dumps({"ok": False, "message": str(e)}, ensure_ascii=False).encode("utf-8"), status=400, content_type="application/json; charset=utf-8")

    # ---------- 其他页面 ----------
    def authors(self) -> None:
        with conn() as c:
            rows = c.execute(
                "SELECT platform,author,author_url,COUNT(*) cnt,AVG(like_count) avg_like,MAX(like_count) max_like,group_concat(tags) all_tags FROM materials WHERE author!='' GROUP BY platform,author,author_url ORDER BY cnt DESC,max_like DESC"
            ).fetchall()
        if rows:
            body = "<h1>作者 / 账号库</h1><div class='sub'>自动沉淀发布者信息，可直接跳转主页。</div><div class='card'><table><tr><th>平台</th><th>作者</th><th>已采集</th><th>平均点赞</th><th>最高点赞</th><th>主要标签</th><th>主页</th></tr>"
            for r in rows:
                tags = []
                for t in (r["all_tags"] or "").split(","):
                    t = t.strip()
                    if t and t not in tags:
                        tags.append(t)
                    if len(tags) >= 6:
                        break
                open_btn = f'<a class="btn small" href="{esc(r["author_url"])}" target="_blank">打开主页</a>' if r["author_url"] else '<span class="muted">未采集</span>'
                body += f"<tr><td>{esc(r['platform'])}</td><td><b>{esc(r['author'])}</b></td><td>{r['cnt']}</td><td>{fmt_count(r['avg_like'])}</td><td>{fmt_count(r['max_like'])}</td><td>{esc(' / '.join(tags))}</td><td>{open_btn}</td></tr>"
            body += "</table></div>"
        else:
            body = "<h1>作者 / 账号库</h1><div class='sub'>自动沉淀发布者信息，可直接跳转主页。</div><div class='card muted'>暂无作者数据。</div>"
        self.send_bytes(page_layout("作者/账号库", body, "作者/账号库"))

    def topics(self) -> None:
        with conn() as c:
            rows = c.execute("SELECT t.*,m.url,m.platform FROM topics t LEFT JOIN materials m ON t.material_id=m.id ORDER BY t.id DESC").fetchall()
        if rows:
            body = "<h1>选题库</h1><div class='sub'>从素材详情页一键加入，形成二创生产流程。</div><div class='card'><table><tr><th>选题标题</th><th>参考作者</th><th>状态</th><th>发布平台</th><th>参考视频</th><th>时间</th></tr>"
            for r in rows:
                body += f"<tr><td><b>{esc(r['title'])}</b><br><span class='muted'>{esc((r['rewritten_copy'] or '')[:80])}</span></td><td>{esc(r['reference_author'])}</td><td>{esc(r['status'])}</td><td>{esc(r['publish_platform'])}</td><td><a class='btn small' href='{esc(r['url'] or '#')}' target='_blank'>打开</a></td><td>{esc(r['created_at'])}</td></tr>"
            body += "</table></div>"
        else:
            body = "<h1>选题库</h1><div class='sub'>从素材详情页一键加入，形成二创生产流程。</div><div class='card muted'>暂无选题。打开某个素材详情，点击“一键加入选题库”。</div>"
        self.send_bytes(page_layout("选题库", body, "选题库"))

    def analytics(self) -> None:
        with conn() as c:
            p = c.execute("SELECT platform,COUNT(*) n FROM materials GROUP BY platform ORDER BY n DESC").fetchall()
            cat = c.execute("SELECT category,COUNT(*) n FROM materials GROUP BY category ORDER BY n DESC").fetchall()
            status = c.execute("SELECT status,COUNT(*) n FROM materials GROUP BY status ORDER BY n DESC").fetchall()
            top_collect = c.execute("SELECT * FROM materials ORDER BY collect_count DESC LIMIT 8").fetchall()
            top_share = c.execute("SELECT * FROM materials ORDER BY share_count DESC LIMIT 8").fetchall()
        body = f"""
<h1>数据看板</h1><div class="sub">平台、分类、状态和高价值素材排行。</div>
<div class="grid3"><div class="card"><h2>平台数量</h2>{self.table_simple(p,['platform','n'],['平台','数量'])}</div><div class="card"><h2>分类数量</h2>{self.table_simple(cat,['category','n'],['分类','数量'])}</div><div class="card"><h2>状态数量</h2>{self.table_simple(status,['status','n'],['状态','数量'])}</div></div>
<div class="grid2"><div class="card"><h2>最高收藏排行</h2>{self.table_materials(top_collect)}</div><div class="card"><h2>最高转发排行</h2>{self.table_materials(top_share)}</div></div>
"""
        self.send_bytes(page_layout("数据看板", body, "数据看板"))

    def reporting_setup(self) -> None:
        with conn() as c:
            logs = c.execute("SELECT * FROM reporting_logs ORDER BY id DESC LIMIT 20").fetchall()
            fails = c.execute("SELECT * FROM failed_imports ORDER BY id DESC LIMIT 10").fetchall()
        log_rows = ""
        for r in logs:
            msg = esc(r["message"])
            raw = esc((r["raw_body"] or "")[:500])
            preview = esc((r["parsed_preview"] or "")[:500])
            log_rows += f"<tr><td>{esc(r['created_at'])}</td><td>{esc(r['status'])}</td><td>入库 {r['inserted_count']} / 失败 {r['failed_count']}<br><span class='muted'>{msg}</span></td><td><details><summary>查看</summary><div class='pre'>{preview}\n\n原始：{raw}</div></details></td></tr>"
        if not log_rows:
            log_rows = "<tr><td colspan='4' class='muted'>暂无上报记录。社媒助手点击“数据上报”后，这里应该马上出现记录。</td></tr>"
        fail_rows = ""
        for f in fails:
            fail_rows += f"<tr><td>{esc(f['created_at'])}</td><td>{esc(f['platform'])}</td><td>{esc(f['title'] or f['url'])}</td><td>{esc(f['reason'])}</td></tr>"
        if not fail_rows:
            fail_rows = "<tr><td colspan='4' class='muted'>暂无失败入库记录。</td></tr>"
        body = f"""
<h1>数据上报</h1><div class="sub">用于对接社媒助手的「数据上报」。V6.9 已加入上报日志：如果社媒助手提示成功但素材库没数据，先看这里的记录和失败原因。</div>
<div class="card"><h2>社媒助手里这样配置</h2>
<table><tr><th>配置项</th><th>填写内容</th></tr>
<tr><td>规则名称</td><td>短视频素材同步</td></tr>
<tr><td>接口地址</td><td><code>http://127.0.0.1:8000/reporting</code></td></tr>
<tr><td>请求方法</td><td>POST</td></tr>
<tr><td>请求头</td><td><code>Content-Type</code> = <code>application/json; charset=utf-8</code></td></tr>
</table>
<div class="alert">重点：在社媒助手“自定义上报字段”里必须勾选「封面图 / 封面图链接 / note_cover」之一；否则本站严格封面模式不会入库。</div>
</div>
<div class="card"><h2>最近上报日志</h2><table><tr><th>时间</th><th>状态</th><th>结果</th><th>内容预览</th></tr>{log_rows}</table></div>
<div class="card"><h2>最近失败入库原因</h2><table><tr><th>时间</th><th>平台</th><th>标题/链接</th><th>原因</th></tr>{fail_rows}</table></div>
<div class="card"><h2>建议勾选字段</h2>
<div class="pre">视频/笔记链接、标题、内容/文案、封面图/封面图链接、作者/博主昵称、作者主页/博主主页、发布时间、点赞量、评论量、收藏量、转发量、播放量、话题标签、视频播放链接/下载链接、数据更新时间。</div>
</div>
<div class="card"><h2>接口说明</h2>
<div class="pre">支持接口：
POST /reporting
POST /api/import/social-assistant
POST /api/import/social_assistant

兼容格式：
{{
  "extra": {{}},
  "meta": [{{"key":"title","name":"标题","alias":"视频标题"}}],
  "list": [{{"title":"示例标题","url":"https://...","note_cover":"https://..."}}],
  "remark": "备注",
  "version": "3.0.1"
}}

如果社媒助手提示成功但这里没有“最近上报日志”，说明请求没有打到当前运行的网站，常见原因：
1. 你没有运行新版网站；
2. 地址填错；
3. 运行了两个不同版本，社媒助手打到了另一个 8000；
4. 社媒助手不是在本机浏览器发请求，127.0.0.1 指向了别的机器。</div>
</div>
"""
        self.send_bytes(page_layout("数据上报", body, "数据上报"))

    def settings(self) -> None:
        body = """
<h1>设置</h1><div class="sub">当前为 Python 3.14 标准库版，本地 SQLite 存储。已支持社媒助手数据上报：/reporting</div>
<div class="card"><h2>采集策略</h2><div class="pre">严格封面模式：开启。\n没有真实封面或页面截图的素材不会进入素材库。\n待补采队列：开启。\n建议开启浏览器插件自动补采：开启。\n数据库位置：data/app.db\n封面保存位置：data/covers/</div></div>
<div class="card"><h2>AI能力说明</h2><div class="pre">当前内置本地模板版 AI 总结、爆款分析、文案改写。\n如后续需要接入大模型 API，可以继续扩展 settings 表和 rewrite/analyze 接口。</div></div>
"""
        self.send_bytes(page_layout("设置", body, "设置"))

    def help(self) -> None:
        body = """
<h1>帮助</h1><div class="sub">重点：现在推荐使用「网站录入链接 + 浏览器采集助手自动补全」的方式。</div>
<div class="card"><h2>运行方法</h2><div class="pre">1. 双击「一键启动.bat」\n2. 浏览器打开 http://127.0.0.1:8000\n3. 先不要关闭黑色命令行窗口</div></div>
<div class="card"><h2>安装浏览器采集助手</h2><div class="pre">1. 打开 Chrome / Edge 浏览器。\n2. 地址栏输入：chrome://extensions 或 edge://extensions\n3. 打开「开发者模式」。\n4. 点击「加载已解压的扩展程序」。\n5. 选择本项目里的 extension 文件夹。\n6. 点开扩展弹窗，开启「自动采集待补采链接」。\n7. 先在网站的「链接采集」页贴链接。\n8. 之后只需回到网站“链接采集”页粘贴分享文本，插件会自动打开待采集链接。\n\n扩展会轮询本地网站的待采集队列，自动打开链接。页面加载后会读取页面可见信息，并把当前页面截图保存为封面，再回传给本地网站。</div></div>
<div class="card"><h2>为什么现在要走「待补采 + 自动补全」？</h2><div class="pre">部分平台页面需要登录、动态渲染或 App 跳转，服务器只拿到链接时看不到浏览器里已经展示的内容。\n所以系统现在改成两段式：\n- 第一步：网站先记录链接，进入待补采队列。\n- 第二步：浏览器助手在你打开原页面时自动补采封面、作者主页、点赞、评论、收藏、转发、发布时间、正文文案。\n\n这版不会再用假的平台色块当封面。</div></div>
"""
        self.send_bytes(page_layout("帮助", body, "帮助"))


def run() -> None:
    print("=" * 60)
    print("短视频素材收集分析平台 V6.9 社媒助手上报诊断修复版 已启动")
    print(f"访问地址：http://{HOST}:{PORT}")
    print("如果端口被占用，请先关闭旧版黑色窗口，或按 Ctrl+C 停止旧服务。")
    print("=" * 60)
    ThreadingHTTPServer((HOST, PORT), App).serve_forever()


if __name__ == "__main__":
    run()
