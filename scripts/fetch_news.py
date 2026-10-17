"""매일 아침 뉴스 브리핑 생성기.

NYT · 워싱턴포스트 · 한국경제 RSS에서 오늘 기사 후보를 모은 뒤,
Claude에게 신문별 중요 기사 5개를 고르고 한국어로 요약(영문은 번역)하게 해
docs/data/ 아래에 JSON으로 저장합니다.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import anthropic
import feedparser
import httpx

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
MODEL = "claude-opus-5-5"
PICKS = 5
MAX_CANDIDATES = 40
USER_AGENT = "Mozilla/5.0 (compatible; MorningBrief/1.0)"

GOOGLE_NEWS = "https://news.google.com/rss/search?q=site:{site}+when:1d&hl=en-US&gl=US&ceid=US:en"

SOURCES = [
    {
        "id": "nyt",
        "name": "뉴욕타임즈",
        "name_en": "The New York Times",
        "lang": "en",
        "feeds": [
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        ],
        "fallback": GOOGLE_NEWS.format(site="nytimes.com"),
    },
    {
        "id": "wapo",
        "name": "워싱턴포스트",
        "name_en": "The Washington Post",
        "lang": "en",
        "feeds": [
            "https://feeds.washingtonpost.com/rss/national",
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.washingtonpost.com/rss/politics",
            "https://feeds.washingtonpost.com/rss/business",
        ],
        # 공식 피드가 자주 502를 내서 구글 뉴스 검색 피드를 예비로 둡니다.
        "fallback": GOOGLE_NEWS.format(site="washingtonpost.com"),
    },
    {
        "id": "hankyung",
        "name": "한국경제",
        "name_en": "The Korea Economic Daily",
        "lang": "ko",
        "feeds": [
            "https://www.hankyung.com/feed/economy",
            "https://www.hankyung.com/feed/finance",
            "https://www.hankyung.com/feed/realestate",
            "https://www.hankyung.com/feed/it",
            "https://www.hankyung.com/feed/international",
            "https://www.hankyung.com/feed/politics",
            "https://www.hankyung.com/feed/all-news",
        ],
        "fallback": None,
    },
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "후보 목록의 번호"},
                    "title_ko": {"type": "string"},
                    "summary_ko": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["index", "title_ko", "summary_ko", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["articles"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 한국 독자를 위한 아침 신문 브리핑 편집자입니다.
한 신문사의 오늘 기사 후보 목록(제목과 리드 문장)을 받으면, 그날 지면에서 가장 중요한 기사를 고르고 한국어로 정리합니다.

- 사회적 파급력, 경제·정책적 중요성, 신문이 비중 있게 다룬 정도를 기준으로 고르세요. 같은 사건을 다룬 기사는 하나만 고릅니다.
- 오피니언·칼럼·퍼즐·광고성 기사는 제외합니다.
- title_ko: 자연스러운 한국어 제목. 영문 기사는 번역하되 직역보다 뜻이 잘 통하게 씁니다.
- summary_ko: 2~3문장 한국어 요약. 무슨 일이 있었고 왜 중요한지를 담되, 후보 목록에 주어진 정보만 사용하고 추측으로 사실을 덧붙이지 마세요.
- category: 정치, 경제, 국제, 사회, 기술, 금융, 부동산, 산업 등 짧은 분류 하나.
- 중요도가 높은 순서로 정렬합니다."""


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def collect(feed_urls: list[str], strip_suffix: str | None = None) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=30)
    seen, items = set(), []
    for url in feed_urls:
        try:
            res = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
        except httpx.HTTPError:
            feed = None
        if not feed or not feed.entries:
            print(f"  ! 피드 실패: {url}", file=sys.stderr)
            continue
        for entry in feed.entries:
            title = clean(entry.get("title", ""))
            link = entry.get("link", "")
            if strip_suffix:
                title = title.removesuffix(strip_suffix).strip()
            published = entry_time(entry)
            if not title or not link or title in seen:
                continue
            if published and published < cutoff:
                continue
            seen.add(title)
            items.append({
                "title": title,
                "description": clean(entry.get("summary", ""))[:400],
                "link": link,
                "published": published.isoformat() if published else None,
            })
    return items[:MAX_CANDIDATES]


def gather_candidates(source: dict) -> list[dict]:
    items = collect(source["feeds"])
    if len(items) < PICKS and source["fallback"]:
        print(f"  → 예비 피드 사용: {source['name']}", file=sys.stderr)
        items += collect([source["fallback"]], strip_suffix=f" - {source['name_en']}")
    return items[:MAX_CANDIDATES]


def summarize(client: anthropic.Anthropic, source: dict, candidates: list[dict]) -> list[dict]:
    listing = "\n\n".join(
        f"[{i}] {c['title']}\n{c['description']}" for i, c in enumerate(candidates)
    )
    lang_note = "영문 기사이므로 한국어로 번역해 정리하세요." if source["lang"] == "en" else ""
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"신문: {source['name']} ({source['name_en']})\n"
                f"중요 기사 {PICKS}개를 골라 주세요. {lang_note}\n\n"
                f"<candidates>\n{listing}\n</candidates>"
            ),
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"{source['name']}: 모델이 요청을 거절했습니다")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"{source['name']}: 응답이 잘렸습니다")

    text = next(b.text for b in response.content if b.type == "text")
    picks = json.loads(text)["articles"]

    articles, used = [], set()
    for pick in picks:
        idx = pick["index"]
        if not 0 <= idx < len(candidates) or idx in used:
            continue  # 목록에 없는 번호는 버려서 링크가 항상 실제 기사를 가리키게 함
        used.add(idx)
        c = candidates[idx]
        articles.append({
            "title_ko": pick["title_ko"],
            "title_original": c["title"] if source["lang"] == "en" else None,
            "summary_ko": pick["summary_ko"],
            "category": pick["category"],
            "url": c["link"],
            "published": c["published"],
        })
    return articles[:PICKS]


def main() -> None:
    now = datetime.now(KST)
    client = anthropic.Anthropic()
    briefing = {"date": now.strftime("%Y-%m-%d"), "generated_at": now.isoformat(), "sources": []}

    for source in SOURCES:
        print(f"● {source['name']}", file=sys.stderr)
        candidates = gather_candidates(source)
        print(f"  후보 {len(candidates)}건", file=sys.stderr)
        entry = {"id": source["id"], "name": source["name"], "name_en": source["name_en"], "articles": []}
        if candidates:
            try:
                entry["articles"] = summarize(client, source, candidates)
            except (anthropic.APIError, RuntimeError, ValueError, KeyError) as err:
                print(f"  ! 요약 실패: {err}", file=sys.stderr)
                entry["error"] = "오늘은 이 신문의 브리핑을 만들지 못했어요."
        else:
            entry["error"] = "기사를 불러오지 못했어요."
        briefing["sources"].append(entry)

    if not any(s["articles"] for s in briefing["sources"]):
        sys.exit("모든 신문에서 실패했습니다. 이전 브리핑을 유지합니다.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(briefing, ensure_ascii=False, indent=2)
    (DATA_DIR / f"{briefing['date']}.json").write_text(payload, encoding="utf-8")
    (DATA_DIR / "latest.json").write_text(payload, encoding="utf-8")

    dates = sorted(
        (p.stem for p in DATA_DIR.glob("????-??-??.json")), reverse=True
    )[:30]
    (DATA_DIR / "index.json").write_text(json.dumps(dates), encoding="utf-8")
    print(f"완료: {briefing['date']}", file=sys.stderr)


if __name__ == "__main__":
    main()
