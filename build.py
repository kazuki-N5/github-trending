"""data/ から静的サイト site/ を作り直す。

- site/index.html          日別の一覧（日付タブ・検索つき）
- site/days/<日付>.html     その日のまとめ記事。初めて出たリポジトリは解説を全文載せ、既出はボタンで個別ページへ飛ばす
- site/repos/<key>.html     リポジトリごとの個別ページ（解説と掲載履歴）
- site/assets/likes.js      いいねボタン。いいねはブラウザの localStorage に保存し、index.html#likes で一覧できる

まとめ記事の全文と個別ページの本文は、同じ data/repos/<key>.json から同じ関数で作るので、文章は完全に同じになる。

使い方: python build.py
"""
import html
import json
import re
import sys
from pathlib import Path

from collect import day_lists, repo_key

ROOT = Path(__file__).resolve().parent
DAYS_DIR = ROOT / "data" / "days"
REPOS_DIR = ROOT / "data" / "repos"
SITE = ROOT / "site"

SRC = {"github": "GitHub Trending", "trendshift": "Trendshift", "starhistory": "Star History", "hatena": "はてなブックマーク"}
LIST_ID = {"daily": "d", "weekly": "w", "hatena": "h"}  # ページ内リンク（#d-<key> など）の接頭辞
LIST_NAME = {"daily": "", "weekly": " 週間", "hatena": " はてブ"}  # 掲載履歴などで日付の後ろに付ける
LIST_PILL = {"weekly": "週1回", "hatena": "日本"}  # 一覧の見出しの前に付ける札

# Zenn の記事アイコン風に、リポジトリ名・一言説明・英語の説明文のキーワードから絵文字を1つ決める（上の行ほど優先）
EMOJI = [
    (r"reverse|decompil|binar|逆解析|リバース", "🔍"), (r"job|interview|resume|就活|求人", "💼"), (r"game|ps5|ゲーム", "🎮"),
    (r"file convert|ファイル変換|pdf|word", "📁"), (r"photo|photoshop|image|diffusion|画像", "🖼️"),
    (r"voice|speech|audio|dubb|transcri|音声|吹き替え", "🎙️"), (r"video|film|motion|動画", "🎬"),
    (r"memory|handoff|記憶", "🧠"), (r"plugin|プラグイン", "🧩"), (r"course|learn|roadmap|教程|学べ", "📚"),
    (r"cad|parametric|3d|地球儀", "📐"), (r"\btv\b", "📺"), (r"math|数学", "🧮"), (r"pentest|security|ペネトレーション|監査", "🛡️"),
    (r"search|index|検索", "🔎"), (r"mermaid|diagram|図", "📊"), (r"scien|研究", "🧪"), (r"ios|xcode", "📱"),
    (r"skill|スキル", "🛠️"), (r"model|llm|deepseek|qwen|言語モデル", "🧬"),
    (r"agent|swarm|harness|エージェント", "🤖"), (r"cli|terminal|ターミナル", "⌨️"),
]


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def emoji_of(repo: str, *texts: str) -> str:
    hay = " ".join((repo, *texts))
    return next((e for pat, e in EMOJI if re.search(pat, hay, re.I)), "📦")


def fmt(date: str) -> str:
    _, m, d = date.split("-")
    return f"{int(m)}/{int(d)}"


def label(e: dict) -> str:
    return SRC[e["source"]] + (f" {e['sourceRank']}位" if e.get("sourceRank") else "")


def score(e: dict) -> str:
    """反応の大きさ。GitHub などはスター（増えた数）、はてなブックマークはブックマークした人数。"""
    if e.get("users"):
        return f"{e['users']} users"
    return f"★ {e['stars']}" if e.get("stars") else ""


def load():
    days = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DAYS_DIR.glob("*.json"))]
    repos = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in REPOS_DIR.glob("*.json")}
    # 掲載順（日付 → 毎日のリスト → 週間 → 日本で話題 → 順位）にすべての出現を並べる
    appearances = []
    for d in days:
        for lst, _, entries in day_lists(d):
            for i, e in enumerate(entries):
                appearances.append({**e, "date": d["date"], "list": lst, "pos": i + 1, "key": repo_key(e["repo"])})
    first = {}
    for a in appearances:
        first.setdefault(a["key"], a)
    emoji = {}
    for key, f in first.items():
        descs = " ".join(a.get("desc") or "" for a in appearances if a["key"] == key)
        emoji[key] = emoji_of(display_name(key, repos, f["repo"]), repos.get(key, {}).get("oneLiner", ""), descs)
    return days, repos, appearances, first, emoji


def is_first(a: dict, first: dict) -> bool:
    f = first[a["key"]]
    return (f["date"], f["list"], f["pos"]) == (a["date"], a["list"], a["pos"])


def display_name(key: str, repos: dict, fallback: str) -> str:
    return repos.get(key, {}).get("repo") or fallback


# ---------- 共通パーツ ----------

def header(prefix: str) -> str:
    return f"""<header><div class="wrap bar">
  <a class="logo" href="{prefix}index.html"><span class="mark">GT</span><span class="txt">GitHub トレンド日報</span></a>
  <form class="search" action="{prefix}index.html" method="get">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    <input name="q" type="search" placeholder="リポジトリ名・説明で検索" autocomplete="off">
  </form>
  <a class="likes-link" href="{prefix}index.html#likes">♥<span class="txt">いいね</span><span class="likes-count"></span></a>
</div></header>"""


def like_button(key: str, name: str) -> str:
    """状態（いいね済みか）は likes.js が読み込み時に反映する。index.html の JS 側 likeBtn と同じ形。"""
    return f'<button type="button" class="like" data-key="{esc(key)}" data-repo="{esc(name)}" aria-pressed="false">♡ いいね</button>'


def page(title: str, prefix: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>
{header(prefix)}
{body}
<script src="{prefix}assets/likes.js"></script>
{script}
</body>
</html>
"""


def repo_body(r: dict | None, entry: dict) -> str:
    """解説の本文。まとめ記事と個別ページの両方で使う。"""
    if not r:
        return f"""<p class="missing">解説はまだありません（作成に失敗したか、作成待ちです）。</p>
<p class="en">{esc(entry.get('desc'))}</p>"""
    out = [f'<p class="lead">{esc(r["oneLiner"])}</p>']
    if not r.get("readme", True):
        out.append('<p class="missing">README を読めなかったため、トレンドページの情報だけで書いています。</p>')
    out.append("<h3>何ができるか</h3><ul>" + "".join(f"<li>{esc(x)}</li>" for x in r["features"]) + "</ul>")
    why = esc(r["why"]).replace("推測:", '<span class="guess">推測</span>')
    out.append(f"<h3>なぜ注目されているか</h3><p>{why}</p>")
    out.append(f"<h3>どんな人に役立つか</h3><p>{esc(r['whoFor'])}</p>")
    out.append("<h3>技術的なポイント</h3><ul>" + "".join(f"<li>{esc(x)}</li>" for x in r["tech"]) + "</ul>")
    try_it = r.get("tryIt") or {}
    steps, cmds = try_it.get("steps") or [], try_it.get("commands") or []
    out.append("<h3>試し方</h3>")
    if steps:
        out.append("<ol>" + "".join(f"<li>{esc(x)}</li>" for x in steps) + "</ol>")
    if cmds:
        out.append("<pre><code>" + esc("\n".join(cmds)) + "</code></pre>")
    if not steps and not cmds:
        out.append("<p>README に試し方の記載はありません。</p>")
    return "\n".join(out)


def meta_line(e: dict, r: dict | None) -> str:
    lang = (r or {}).get("language") or e.get("language")
    parts = [f'<span class="src {e["source"]}">{esc(label(e))}</span>']
    if score(e):
        parts.append(f"<span>{esc(score(e))}</span>")
    if lang:
        parts.append(f"<span>{esc(lang)}</span>")
    return "".join(parts)


# ---------- まとめ記事 ----------

def day_page(d: dict, repos: dict, first: dict, emoji: dict) -> str:
    date = d["date"]
    lists = day_lists(d)

    toc, sections, new_count = [], [], 0
    for lst, title, entries in lists:
        rows, cards = [], []
        for i, e in enumerate(entries):
            key = repo_key(e["repo"])
            a = {**e, "date": date, "list": lst, "pos": i + 1, "key": key}
            r = repos.get(key)
            name = display_name(key, repos, e["repo"])
            anchor = f"{LIST_ID[lst]}-{key}"
            new = is_first(a, first)
            new_count += new
            one = (r or {}).get("oneLiner") or e.get("desc") or ""
            rows.append(f"""<tr><td class="n">{i + 1}</td><td><a href="#{anchor}">{esc(name)}</a></td>
<td><span class="src {e['source']}">{esc(label(e))}</span></td><td class="num">{esc(score(e))}</td>
<td>{esc(one)}</td><td>{'<span class="chip new">新規</span>' if new else '<span class="chip dup">既出</span>'}</td></tr>""")
            head = f"""<div class="rhead"><div class="emoji">{emoji[key]}</div><div>
<div class="rank">{i + 1}</div><h2><a href="../repos/{key}.html">{esc(name)}</a></h2>
<div class="meta">{meta_line(e, r)}<a class="gh" href="https://github.com/{esc(name)}" target="_blank" rel="noopener">GitHub ↗</a>{like_button(key, name)}</div></div></div>"""
            if new:
                cards.append(f"""<article class="repo full" id="{anchor}">{head}
<div class="content">{repo_body(r, e)}</div>
<div class="foot"><a href="../repos/{key}.html">このリポジトリの個別ページ →</a></div></article>""")
            else:
                f = first[key]
                cards.append(f"""<article class="repo dup" id="{anchor}">{head}
<p class="lead small">{esc(one)}</p>
<a class="btn" href="../repos/{key}.html">説明を見る<span>（初掲載 {fmt(f['date'])} {esc(label(f))}）</span></a></article>""")
        toc.append(f"""<h2 class="toc-title">{esc(title)}<span class="count">{len(entries)}件</span></h2>
<div class="table"><table><thead><tr><th>#</th><th>リポジトリ</th><th>取得元</th><th>反応</th><th>一言で</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>""")
        sections.append(f'<section id="{lst}"><h2 class="sec">{esc(title)}</h2>{"".join(cards)}</section>')

    total = sum(len(entries) for _, _, entries in lists)
    body = f"""<div class="area"><main class="wrap narrow">
<a class="back" href="../index.html#{date}">← {date} の一覧へ</a>
<h1 class="day-title">{date} のトレンド</h1>
<p class="note">{total}件（新規 {new_count}件・既出 {total - new_count}件）。新規のリポジトリは解説を全文、既出のリポジトリは「説明を見る」から個別ページへ。</p>
<div class="card toc">{''.join(toc)}</div>
{''.join(sections)}
</main></div>"""
    return page(f"{date} のトレンド | GitHub トレンド日報", "../", body)


# ---------- 個別ページ ----------

def repo_page(key: str, repos: dict, appearances: list, first: dict, emoji: dict) -> str:
    f = first[key]
    r = repos.get(key)
    name = display_name(key, repos, f["repo"])
    history = "".join(
        f"""<li><a href="../days/{a['date']}.html#{LIST_ID[a['list']]}-{key}">{a['date']}{LIST_NAME[a['list']]}</a>
<span class="src {a['source']}">{esc(label(a))}</span>{f"<span>{esc(score(a))}</span>" if score(a) else ''}</li>"""
        for a in appearances if a["key"] == key)
    one = (r or {}).get("oneLiner") or f.get("desc") or ""
    body = f"""<div class="area"><main class="wrap narrow">
<article class="card repo-page">
<div class="rhead"><div class="emoji big">{emoji[key]}</div><div>
<h1>{esc(name)}</h1>
<div class="meta">{f'<span>{esc((r or {}).get("language") or f.get("language"))}</span>' if (r or {}).get("language") or f.get("language") else ''}
<span>初掲載 {f['date']}（{esc(label(f))}）</span>
<a class="gh" href="https://github.com/{esc(name)}" target="_blank" rel="noopener">GitHub ↗</a>{like_button(key, name)}</div></div></div>
<div class="content">{repo_body(r, f)}</div>
<h3 class="hist-title">掲載履歴</h3><ul class="history">{history}</ul>
</article>
</main></div>"""
    return page(f"{name} | GitHub トレンド日報", "../", body)


# ---------- 一覧（index.html） ----------

def index_page(days: list, repos: dict, emoji: dict) -> str:
    pick = lambda entries: [{k: e.get(k) for k in ("repo", "source", "sourceRank", "stars", "users", "desc")} for e in entries]
    data = {
        "days": [{
            "date": d["date"],
            "weekly": bool(d.get("weekly")),
            "lists": [{"id": lst, "title": title, "entries": pick(entries)} for lst, title, entries in day_lists(d)],
        } for d in days],
        "repos": {k: {"repo": r.get("repo"), "oneLiner": r.get("oneLiner", ""), "language": r.get("language", "")}
                  for k, r in repos.items()},
        "emoji": emoji,
        "src": SRC, "listId": LIST_ID, "listName": LIST_NAME, "listPill": LIST_PILL,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    body = """<nav class="wrap tabs" id="dates"></nav>
<div class="area"><main class="wrap" id="main"></main></div>"""
    script = "<script>window.TREND = " + payload + ";</script>\n<script>" + INDEX_JS + "</script>"
    return page("GitHub トレンド日報", "", body, script)


INDEX_JS = r"""
const { days, repos, emoji, src: SRC, listId: LIST_ID, listName: LIST_NAME, listPill: LIST_PILL } = window.TREND;
const keyOf = r => r.toLowerCase().replace("/", "__");
const fmt = d => { const [, m, dd] = d.split("-"); return `${+m}/${+dd}`; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const label = a => SRC[a.source] + (a.sourceRank ? ` ${a.sourceRank}位` : "");
const score = e => e.users ? `${e.users} users` : e.stars ? `★ ${e.stars}` : "";
const emojiOf = k => emoji[k] || "📦";
const nameOf = (k, fb) => (repos[k] && repos[k].repo) || fb;

const appearances = [];
for (const d of days)
  for (const l of d.lists)
    l.entries.forEach((e, i) => appearances.push({ ...e, date: d.date, list: l.id, pos: i + 1, key: keyOf(e.repo) }));
const first = new Map();
for (const a of appearances) if (!first.has(a.key)) first.set(a.key, a);
const isFirst = a => { const f = first.get(a.key); return f.date === a.date && f.list === a.list && f.pos === a.pos; };
const oneOf = (k, e) => (repos[k] && repos[k].oneLiner) || (e && e.desc) || "";
const likeBtn = (k, name) => `<button type="button" class="like" data-key="${esc(k)}" data-repo="${esc(name)}" aria-pressed="false">♡ いいね</button>`;

function renderDates(active) {
  document.getElementById("dates").innerHTML = [...days].reverse().map(d =>
    `<a href="#${d.date}" class="${d.date === active ? "active" : ""}">${d.date}${d.weekly ? '<span class="w">週間</span>' : ""}</a>`).join("");
}

function card(e, date, list, pos) {
  const k = keyOf(e.repo), a = { ...e, date, list, pos, key: k }, name = nameOf(k, e.repo);
  const dup = !isFirst(a), f = first.get(k), one = oneOf(k, e);
  return `<article class="item ${dup ? "dupe" : ""}">
    <div class="emoji">${emojiOf(k)}</div>
    <div class="body">
      <div class="title"><a href="repos/${k}.html">${esc(name)}</a></div>
      ${one ? `<div class="desc">${esc(one)}</div>` : ""}
      <div class="meta"><span class="src ${e.source}">${esc(label(e))}</span>
        ${score(e) ? `<span>${esc(score(e))}</span>` : ""}
        ${dup ? `<span class="chip dup">既出</span><span>初掲載 ${fmt(f.date)}</span>` : '<span class="chip new">新規</span>'}
        <a class="gh" href="https://github.com/${esc(name)}" target="_blank" rel="noopener">GitHub ↗</a>${likeBtn(k, name)}</div>
    </div></article>`;
}

function section(title, entries, date, list, extra) {
  const dupCount = entries.filter((e, i) => !isFirst({ ...e, date, list, pos: i + 1, key: keyOf(e.repo) })).length;
  return `<div class="sec-head">${extra || ""}<h2>${esc(title)}</h2><span class="count">${entries.length}件・既出 ${dupCount}件</span>
    <a class="btn" href="days/${date}.html${list === "daily" ? "" : "#" + list}">まとめを読む →</a></div>
    <div class="grid">${entries.map((e, i) => card(e, date, list, i + 1)).join("")}</div>`;
}

function renderDay(date) {
  const d = days.find(x => x.date === date) || days[days.length - 1];
  if (!d) { document.getElementById("main").innerHTML = '<p class="empty">まだデータがありません。</p>'; return; }
  renderDates(d.date);
  let html = `<h1 class="day-title">${d.date}</h1>`;
  for (const l of d.lists)
    html += section(l.title, l.entries, d.date, l.id, LIST_PILL[l.id] ? `<span class="pill ${l.id}">${LIST_PILL[l.id]}</span>` : "");
  document.getElementById("main").innerHTML = html;
  Likes.refresh();
  window.scrollTo(0, 0);
}

function renderSearch(q) {
  const t = q.trim().toLowerCase(), groups = new Map();
  for (const a of appearances) {
    const hay = `${nameOf(a.key, a.repo)} ${oneOf(a.key, a)} ${a.desc || ""}`.toLowerCase();
    if (!hay.includes(t)) continue;
    if (!groups.has(a.key)) groups.set(a.key, []);
    groups.get(a.key).push(a);
  }
  renderDates(null);
  const items = [...groups.entries()]
    .sort(([ka], [kb]) => kb.includes(t) - ka.includes(t))
    .map(([k, list]) => {
      const name = nameOf(k, list[0].repo), one = oneOf(k, list[0]);
      return `<article class="item"><div class="emoji">${emojiOf(k)}</div><div class="body hits">
        <div class="title"><a href="repos/${k}.html">${esc(name)}</a></div>
        ${one ? `<div class="desc">${esc(one)}</div>` : ""}
        <div class="meta"><span class="chip ${list.length > 1 ? "dup" : "new"}">${list.length}回掲載</span>${likeBtn(k, name)}</div>
        <div>${list.map(a => `<a class="ap" href="days/${a.date}.html#${LIST_ID[a.list]}-${k}">${fmt(a.date)}${LIST_NAME[a.list]} ${esc(label(a))}</a>`).join("")}</div>
      </div></article>`;
    });
  document.getElementById("main").innerHTML = `<h1 class="day-title">「${esc(q)}」の検索結果</h1><p class="note">${groups.size}件</p>
    <div class="grid">${items.join("")}</div>${items.length ? "" : '<p class="empty">見つかりませんでした。</p>'}`;
  Likes.refresh();
}

function renderLikes() {
  const liked = Likes.all();
  renderDates(null);
  const items = Object.keys(liked)
    .sort((a, b) => String(liked[b].at).localeCompare(String(liked[a].at)))
    .map(k => {
      const list = appearances.filter(a => a.key === k), at = new Date(liked[k].at);
      const name = nameOf(k, liked[k].repo || (list[0] && list[0].repo) || k), one = oneOf(k, list[0]);
      const lang = repos[k] && repos[k].language;
      const title = list.length ? `<a href="repos/${k}.html">${esc(name)}</a>` : esc(name);
      return `<article class="item"><div class="emoji">${emojiOf(k)}</div><div class="body hits">
        <div class="title">${title}</div>
        ${one ? `<div class="desc">${esc(one)}</div>` : ""}
        <div class="meta">${isNaN(at) ? "" : `<span>いいね ${at.getMonth() + 1}/${at.getDate()}</span>`}
          ${lang ? `<span>${esc(lang)}</span>` : ""}
          ${list.length ? `<span>初掲載 ${fmt(list[0].date)}・${list.length}回掲載</span>` : ""}
          <a class="gh" href="https://github.com/${esc(name)}" target="_blank" rel="noopener">GitHub ↗</a>${likeBtn(k, name)}</div>
      </div></article>`;
    });
  document.getElementById("main").innerHTML = `<h1 class="day-title">いいねしたリポジトリ</h1>
    <p class="note">${items.length}件（新しくいいねした順）。いいねはこのブラウザに保存されます。外したものは次にこのページを開いたときに消えます。</p>
    <div class="grid">${items.join("")}</div>${items.length ? "" : '<p class="empty">まだいいねしたリポジトリはありません。カードの「♡ いいね」で追加できます。</p>'}`;
  Likes.refresh();
  window.scrollTo(0, 0);
}

const qEl = document.querySelector('.search input');
document.querySelector('.search').addEventListener("submit", ev => ev.preventDefault());
qEl.addEventListener("input", () => qEl.value.trim() ? renderSearch(qEl.value) : route());
function route() {
  if (location.hash && qEl.value) qEl.value = "";
  const h = decodeURIComponent(location.hash.slice(1));
  h === "likes" ? renderLikes() : renderDay(h);
}
window.addEventListener("hashchange", route);
const initial = new URLSearchParams(location.search).get("q");
if (initial) { qEl.value = initial; renderSearch(initial); } else route();
"""

# 全ページ共通。いいねは localStorage の "gt-likes" に {key: {repo, at}} で保存する
LIKES_JS = r"""
(() => {
  const STORE = "gt-likes";
  const all = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
  function refresh() {
    const liked = all();
    document.querySelectorAll(".like[data-key]").forEach(b => {
      const on = b.dataset.key in liked;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on);
      b.textContent = on ? "♥ いいね済み" : "♡ いいね";
    });
    const n = Object.keys(liked).length;
    document.querySelectorAll(".likes-count").forEach(el => el.textContent = n || "");
  }
  function toggle(key, repo) {
    const liked = all();
    if (liked[key]) delete liked[key]; else liked[key] = { repo, at: new Date().toISOString() };
    localStorage.setItem(STORE, JSON.stringify(liked));
    refresh();
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest(".like[data-key]");
    if (b) { ev.preventDefault(); toggle(b.dataset.key, b.dataset.repo); }
  });
  window.addEventListener("storage", ev => { if (ev.key === STORE) refresh(); });
  window.Likes = { all, refresh };
  refresh();
})();
"""

CSS = """
:root { --text: rgba(0,0,0,.82); --muted: #8f9faa; --sub: #65717b; --line: #e4edf4; --soft: #f1f5f9;
  --primary: #3ea8ff; --primary-soft: #eaf6ff; --gh: #24292f; --ts: #7c5cff; --sh: #e9a020; --dup: #f07c4a; --new: #1ea672; --like: #f2547d;
  --hb: #00a4de; }
* { box-sizing: border-box; }
body { margin: 0; color: var(--text); background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic UI", Meiryo, sans-serif; }
a { color: inherit; text-decoration: none; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 0 24px; }
.wrap.narrow { max-width: 860px; }
header { background: #fff; }
.bar { display: flex; align-items: center; gap: 16px; height: 64px; }
.logo { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 20px; }
.logo .mark { width: 28px; height: 28px; border-radius: 8px; background: var(--primary); color: #fff; display: grid; place-items: center; font-size: 13px; }
.search { margin-left: auto; position: relative; width: 340px; }
.search input { width: 100%; height: 40px; border: 1px solid var(--line); background: var(--soft); border-radius: 99px; padding: 0 16px 0 40px; font-size: 14px; color: var(--text); outline: none; }
.search input:focus { background: #fff; border-color: var(--primary); }
.search svg { position: absolute; left: 14px; top: 12px; width: 16px; height: 16px; color: var(--muted); }
.likes-link { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 700; color: var(--like); white-space: nowrap; }
.likes-link .txt { color: var(--sub); }
.likes-link:hover .txt { color: var(--text); }
.likes-count:not(:empty) { background: var(--like); color: #fff; border-radius: 99px; padding: 0 7px; font-size: 12px; line-height: 18px; }
.like { margin-left: auto; display: inline-flex; align-items: center; border: 1px solid var(--line); background: #fff; color: var(--sub); border-radius: 99px; padding: 2px 10px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }
.like:hover { border-color: var(--like); color: var(--like); }
.like.on { background: var(--like); border-color: var(--like); color: #fff; }
.tabs { display: flex; gap: 28px; overflow-x: auto; border-bottom: 1px solid var(--line); }
.tabs a { padding: 10px 0 12px; font-size: 15px; font-weight: 600; color: var(--muted); border-bottom: 2px solid transparent; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
.tabs a.active { color: var(--text); border-bottom-color: var(--text); }
.tabs .w, .pill.weekly { font-size: 11px; font-weight: 700; color: var(--sh); background: #fff6e3; border-radius: 99px; padding: 1px 8px; }
.pill.hatena { font-size: 11px; font-weight: 700; color: var(--hb); background: #e3f5fc; border-radius: 99px; padding: 1px 8px; }
.area { background: var(--soft); min-height: calc(100vh - 64px); padding: 36px 0 72px; border-top: 1px solid var(--line); }
.day-title { font-size: 28px; font-weight: 700; margin: 0 0 6px; }
.note { font-size: 13px; color: var(--sub); margin: 0 0 8px; line-height: 1.7; }
.empty { color: var(--sub); }
.sec-head { display: flex; align-items: center; gap: 10px; margin: 36px 0 18px; flex-wrap: wrap; }
.sec-head h2 { margin: 0; font-size: 24px; }
.count { font-size: 13px; color: var(--sub); font-weight: 400; margin-left: 8px; }
.btn { display: inline-flex; align-items: center; gap: 6px; background: var(--primary); color: #fff; font-weight: 700; font-size: 14px; border-radius: 99px; padding: 8px 18px; }
.btn:hover { filter: brightness(1.05); }
.btn span { font-weight: 400; font-size: 12px; opacity: .9; }
.sec-head .btn { margin-left: auto; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 28px; }
.item { display: flex; gap: 16px; padding: 14px; border-radius: 14px; }
.emoji { flex: none; width: 78px; height: 78px; border-radius: 14px; background: #fff; display: grid; place-items: center; font-size: 36px; }
.emoji.big { width: 96px; height: 96px; font-size: 46px; background: var(--soft); }
.body { min-width: 0; flex: 1; }
.title { font-size: 16px; font-weight: 700; line-height: 1.5; word-break: break-all; }
.title a:hover, .repo h2 a:hover { text-decoration: underline; }
.item.dupe .title { color: var(--sub); }
.desc { font-size: 13px; color: var(--sub); line-height: 1.6; margin-top: 4px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; margin-top: 8px; font-size: 12px; color: var(--muted); }
.gh { color: var(--primary); font-weight: 600; }
.src { font-weight: 700; white-space: nowrap; }
.src.github { color: var(--gh); } .src.trendshift { color: var(--ts); } .src.starhistory { color: var(--sh); } .src.hatena { color: var(--hb); }
.chip { font-size: 11px; font-weight: 700; border-radius: 99px; padding: 1px 8px; white-space: nowrap; }
.chip.dup { color: var(--dup); background: #fff1ea; }
.chip.new { color: var(--new); background: #e5f7ef; }
.hits a.ap { display: inline-block; margin: 6px 6px 0 0; font-size: 12px; font-weight: 600; color: var(--primary); background: #fff; border: 1px solid var(--line); border-radius: 99px; padding: 3px 10px; }
.back { display: inline-block; font-size: 13px; color: var(--primary); font-weight: 600; margin-bottom: 14px; }
.card { background: #fff; border-radius: 14px; padding: 28px 32px; }
.toc { margin: 24px 0 8px; }
.toc-title { font-size: 18px; margin: 0 0 12px; }
.toc-title + .table { margin-bottom: 24px; }
.table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; font-size: 12px; white-space: nowrap; }
td.n { color: var(--muted); width: 28px; }
td.num { white-space: nowrap; color: var(--sub); }
td a { color: var(--primary); font-weight: 600; overflow-wrap: anywhere; }
td:nth-child(2) { min-width: 200px; }
td:nth-child(3) { white-space: nowrap; }
h2.sec { font-size: 24px; margin: 48px 0 16px; }
.repo { background: #fff; border-radius: 14px; padding: 28px 32px; margin-bottom: 20px; scroll-margin-top: 16px; }
.repo:target { box-shadow: 0 0 0 2px var(--primary); }
.repo.dup { padding: 20px 32px; }
.rhead { display: flex; gap: 18px; align-items: center; }
.rhead .rank { font-size: 12px; font-weight: 700; color: var(--muted); }
.repo h2 { font-size: 22px; margin: 2px 0 0; word-break: break-all; }
.repo.dup h2 { font-size: 18px; color: var(--sub); }
.repo-page h1 { font-size: 26px; margin: 0; word-break: break-all; }
.content { margin-top: 18px; line-height: 1.9; font-size: 15px; }
.content h3, .hist-title { font-size: 18px; margin: 28px 0 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.content ul, .content ol { padding-left: 1.4em; margin: 6px 0; }
.content li { margin: 4px 0; }
.lead { font-size: 17px; font-weight: 700; margin: 0; }
.lead.small { font-size: 14px; font-weight: 400; color: var(--sub); margin: 12px 0 14px; }
.guess { font-size: 11px; font-weight: 700; color: var(--sh); background: #fff6e3; border-radius: 99px; padding: 1px 8px; margin-right: 4px; }
pre { background: #1e2733; color: #e6edf3; border-radius: 10px; padding: 14px 16px; overflow-x: auto; font-size: 13px; line-height: 1.6; }
.missing { color: var(--dup); font-size: 14px; }
.en { color: var(--sub); font-size: 14px; }
.foot { margin-top: 20px; text-align: right; font-size: 14px; }
.foot a { color: var(--primary); font-weight: 600; }
.history { list-style: none; padding: 0; margin: 0; font-size: 14px; }
.history li { display: flex; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.history a { color: var(--primary); font-weight: 600; }
@media (max-width: 760px) {
  .grid { grid-template-columns: 1fr; }
  .search { width: auto; flex: 1; }
  .logo .txt, .likes-link .txt { display: none; }
  .card, .repo { padding: 20px; }
}
"""


def main() -> int:
    days, repos, appearances, first, emoji = load()
    # site/ 自体は消さない（エクスプローラーやサーバーが開いていると削除に失敗するため）。古いページだけ消す
    for sub in ("assets", "days", "repos"):
        (SITE / sub).mkdir(parents=True, exist_ok=True)
    for sub in ("days", "repos"):
        for old in (SITE / sub).glob("*.html"):
            old.unlink()
    (SITE / "assets" / "style.css").write_text(CSS.lstrip(), encoding="utf-8")
    (SITE / "assets" / "likes.js").write_text(LIKES_JS.lstrip(), encoding="utf-8")
    (SITE / "index.html").write_text(index_page(days, repos, emoji), encoding="utf-8")
    for d in days:
        (SITE / "days" / f"{d['date']}.html").write_text(day_page(d, repos, first, emoji), encoding="utf-8")
    for key in first:
        (SITE / "repos" / f"{key}.html").write_text(repo_page(key, repos, appearances, first, emoji), encoding="utf-8")
    missing = [k for k in first if k not in repos]
    print(f"日別 {len(days)}ページ・個別 {len(first)}ページを作成"
          + (f"（解説が無いもの {len(missing)}件: {', '.join(missing)}）" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
