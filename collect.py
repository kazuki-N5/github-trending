"""その日のトレンドを集めて data/days/<日付>.json に保存し、説明がまだ無いリポジトリを data/pending.json に書き出す。

毎日のリスト: GitHub Trending 上位15件 + Trendshift のうち GitHub とかぶらないもの。合計20件にそろえる。
週1回（月曜、または --weekly 指定時）: Star History の週間ランキング上位20件も取る。
日本で話題: はてなブックマークで GitHub のリポジトリに付いたブックマークの新着から、HATENA_MIN_USERS 人以上のものを最大10件。過去に載せたものは除く。

使い方: python collect.py [--date YYYY-MM-DD] [--weekly]
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAYS_DIR = ROOT / "data" / "days"
REPOS_DIR = ROOT / "data" / "repos"
PENDING = ROOT / "data" / "pending.json"

DAILY_TOTAL = 20
GITHUB_MAX = 15
WEEKLY_TOTAL = 20
WEEKLY_WEEKDAY = 0  # 月曜日（月曜=0）
JST = dt.timezone(dt.timedelta(hours=9))  # クラウド（UTC）で動かしても日本の日付になるようにする
# 日本で話題: はてなブックマークの「github.com の新着エントリー」RSS（直近数日の30件）から拾う
HATENA_RSS = "https://b.hatena.ne.jp/site/github.com/?mode=rss"
HATENA_MIN_USERS = 3
HATENA_TOTAL = 10
# github.com/<これ>/<名前> の形でもリポジトリではない URL
GITHUB_RESERVED = {"about", "apps", "collections", "customer-stories", "enterprise", "events", "features", "marketplace",
                   "organizations", "orgs", "readme", "resources", "security", "settings", "site", "solutions", "sponsors",
                   "topics", "users"}
# リポジトリのトップか README のページだけをリポジトリの紹介とみなす（issue やファイル単体へのブックマークは除く）
REPO_URL = re.compile(r"https?://github\.com/([\w-]+)/([\w.-]+?)(?:\.git)?/?(?:#.*|/blob/[^/]+/README[^/]*)?$", re.I)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def repo_key(repo: str) -> str:
    """data/repos/ と site/repos/ のファイル名に使うキー。GitHub の名前は大文字小文字を区別しない。"""
    return repo.lower().replace("/", "__")


def day_lists(day: dict) -> list[tuple[str, str, list]]:
    """その日のリストを掲載順に（種類, 見出し, entries）で返す。週間・日本で話題はある日だけ。"""
    out = [("daily", "毎日のリスト", day["entries"])]
    for lst in ("weekly", "hatena"):
        if (day.get(lst) or {}).get("entries"):
            out.append((lst, day[lst]["label"], day[lst]["entries"]))
    return out


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def github_trending() -> list[dict]:
    try:
        page = fetch("https://github.com/trending?since=daily")
    except Exception as e:
        print(f"GitHub Trending の取得をスキップ: {e}", file=sys.stderr)
        return []
    items = []
    for row in page.split('<article class="Box-row">')[1:]:
        name = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', row)
        if not name:
            continue
        repo = name.group(1)
        desc = re.search(r'<p class="col-9[^"]*">([\s\S]*?)</p>', row)
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', row)
        total = re.search(rf'href="/{re.escape(repo)}/stargazers"[^>]*>([\s\S]*?)</a>', row)
        today = re.search(r"([\d,]+)\s+stars?\s+today", row)
        items.append({
            "repo": repo,
            "source": "github",
            "sourceRank": len(items) + 1,
            "desc": text_of(desc.group(1)) if desc else "",
            "language": lang.group(1).strip() if lang else "",
            "starsTotal": text_of(total.group(1)) if total else "",
            "stars": f"+{today.group(1)}" if today else "",
        })
    return items


def trendshift() -> list[dict]:
    page = fetch("https://trendshift.io/")
    for block in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', page):
        data = json.loads(block)
        if "itemListElement" not in data:
            continue
        items = []
        for el in data["itemListElement"]:
            it = el["item"]
            items.append({
                "repo": it["name"],
                "source": "trendshift",
                "sourceRank": el["position"],
                "desc": it.get("description", ""),
                "language": it.get("programmingLanguage", ""),
                "starsTotal": "",
                "stars": "",  # 増えたスター数はページ側で後から描画されるため、取得時点の HTML には無い
            })
        return items
    raise RuntimeError("Trendshift のランキング（ld+json）が見つからない")


def star_history_weekly() -> dict:
    page = fetch("https://www.star-history.com/")
    period = re.search(r"Updated\s*(?:<!-- -->)?\s*([^<]+?)\s*</", page)
    items = []
    for m in re.finditer(r'<li class="relative group"><a href="/([^"/]+/[^"/]+)"([\s\S]*?)</li>', page):
        gained = re.findall(r"\+[\d,]+", text_of(m.group(2)))
        items.append({
            "repo": m.group(1),
            "source": "starhistory",
            "sourceRank": len(items) + 1,
            "desc": "",
            "language": "",
            "starsTotal": "",
            "stars": f"{gained[-1]}（週）" if gained else "",
        })
        if len(items) == WEEKLY_TOTAL:
            break
    if not items:
        raise RuntimeError("Star History の週間ランキングが見つからない")
    label = text_of(period.group(1)) if period else ""
    return {"label": f"Star History 週間（{label}）" if label else "Star History 週間", "entries": items}


def hatena_github(exclude: set[str]) -> dict:
    """はてなブックマークで最近ブックマークされた GitHub リポジトリを、ブックマーク数の多い順に拾う。

    RSS は新しいエントリー順に直近数日分しか出ないので、毎日見て HATENA_MIN_USERS 人に届いたものから載せる。
    exclude（repo_key）に入っているものは除く。
    """
    page = fetch(HATENA_RSS)
    found = {}
    for item in re.findall(r"<item[\s\S]*?</item>", page):
        url = REPO_URL.match(html.unescape(re.search(r"<link>([^<]*)</link>", item).group(1)))
        users = int(re.search(r"<hatena:bookmarkcount>(\d+)<", item).group(1))
        if not url or url.group(1).lower() in GITHUB_RESERVED or users < HATENA_MIN_USERS:
            continue
        repo = f"{url.group(1)}/{url.group(2)}"
        if repo_key(repo) in exclude or found.get(repo_key(repo), {}).get("users", 0) >= users:
            continue
        title = html.unescape(re.search(r"<title>([^<]*)</title>", item).group(1))
        found[repo_key(repo)] = {
            "repo": repo,
            "source": "hatena",
            "desc": re.sub(rf"^GitHub - {re.escape(repo)}:?\s*", "", title, flags=re.I),  # 「GitHub - owner/repo: 説明」の説明部分
            "language": "",
            "starsTotal": "",
            "stars": "",
            "users": users,
        }
    items = sorted(found.values(), key=lambda e: -e["users"])[:HATENA_TOTAL]
    for i, e in enumerate(items):
        e["sourceRank"] = i + 1
    return {"label": "日本で話題（はてなブックマーク）", "entries": items}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(JST).date().isoformat())
    ap.add_argument("--weekly", action="store_true", help="曜日に関係なく Star History も取る")
    args = ap.parse_args()
    weekly = args.weekly or dt.date.fromisoformat(args.date).weekday() == WEEKLY_WEEKDAY

    gh = github_trending()[:GITHUB_MAX]
    seen = {e["repo"].lower() for e in gh}
    fill = [e for e in trendshift() if e["repo"].lower() not in seen][: DAILY_TOTAL - len(gh)]
    day = {
        "date": args.date,
        "collectedAt": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "entries": gh + fill,
    }
    if weekly:
        day["weekly"] = star_history_weekly()
    # 過去の日に載せたものは除く（同じ日の再実行では同じ結果になるよう、今日のファイルは見ない）
    shown = {repo_key(e["repo"]) for p in DAYS_DIR.glob("*.json") if p.stem != args.date
             for _, _, entries in day_lists(json.loads(p.read_text(encoding="utf-8"))) for e in entries}
    shown |= {repo_key(e["repo"]) for _, _, entries in day_lists(day) for e in entries}
    day["hatena"] = hatena_github(shown)

    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    (DAYS_DIR / f"{args.date}.json").write_text(json.dumps(day, ensure_ascii=False, indent=2), encoding="utf-8")

    # 説明ファイルがまだ無いリポジトリだけを、AI に書いてもらう対象にする
    pending, keys = [], set()
    for e in (e for _, _, entries in day_lists(day) for e in entries):
        k = repo_key(e["repo"])
        if k in keys or (REPOS_DIR / f"{k}.json").exists():
            continue
        keys.add(k)
        pending.append({"repo": e["repo"], "key": k, "desc": e["desc"], "language": e["language"]})
    PENDING.write_text(json.dumps({"date": args.date, "repos": pending}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{args.date}: 毎日 {len(day['entries'])}件"
          f"{'・週間 ' + str(len(day['weekly']['entries'])) + '件' if weekly else ''}"
          f"・日本で話題 {len(day['hatena']['entries'])}件"
          f"・説明が必要な新規 {len(pending)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
