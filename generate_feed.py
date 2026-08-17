#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
taiwansanpo.com の公開記事ページから Nordot Feed（RSS入稿用XML）を生成する。

背景（重要）:
  Jimdo純正RSS(/rss/blog)にはNordot非互換のバグがある（未来日付pubDate混入・
  本文が上限3万字超・直近18件のみ）。過去にこれが原因で配信が失敗したため、
  Jimdo RSSは一切使わず、記事ページのHTMLから直接この専用フィードを生成する。

仕様: https://nordotapp.notion.site/Nordot-Feed-2553915055aa80958288f769d8037754
  - item は nordot:fedAt の降順。fedAt は入稿(変更)時刻で、未来日付は禁止。
  - 過去記事は publishedAt に元の公開日(過去日付)を入れると、その日付で公開される。
  - 1フィードに含めるのは20本程度まで。本文は最大30,000字。
  - 本文(nordot_html)に使える要素: h1-h6 p ul ol li blockquote pre hr figure
    figcaption img / インライン: a br em strong del

使い方:
  articles.json に配信対象を並べて `python3 generate_feed.py` を実行。
  → docs/feed.xml を生成（GitHub Pages の公開対象は docs/）。
  fedAt は feed_state.json に保存し、本文・タイトルが変わった記事だけ更新する。
"""

import json, re, sys, hashlib, subprocess
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent
UNIT_ID = "415341151687509089"  # NordotCMS 設定→システム連携 で確認したユニットID
JST = timezone(timedelta(hours=9))
MAX_BODY = 30000
MAX_ITEMS = 20  # 過去記事入稿は1フィード20本程度まで（Nordot公式ガイド）

BLOCK_KEEP = {"h1","h2","h3","h4","h5","h6","p","ul","ol","li",
              "blockquote","pre","hr","figure","figcaption","img"}
INLINE_KEEP = {"a","br","em","strong","del"}
RENAME = {"b":"strong","i":"em"}
DROP_WITH_CONTENT = {"script","style","noscript","iframe","form","button"}


class Sanitizer(HTMLParser):
    """Jimdo記事の生HTMLをNordotのnordot_html許可タグだけに正規化する。

    - div/span等の非対応タグは剥がして中身のみ残す
    - ただし figure 内の span はクレジット表記なので figcaption に変換
    - style/class等の属性は捨てる（a[href]・img[src]のみ保持）
    - table はNordot非対応のため「セル1：セル2」形式の ul に変換
    """
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []
        self.skip_depth = 0
        self.figure_depth = 0
        self.span_as_figcaption = []  # figure内で開いたspanの変換記録
        self.in_table = 0
        self.row_cells = []
        self.cell_buf = None

    def _attrs(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            href = d["href"]
            if href.startswith("/"):
                href = "https://www.taiwansanpo.com" + href
            return ' href="%s"' % href.replace('"', "&quot;")
        if tag == "img" and d.get("src"):
            src = d["src"]
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = "https://www.taiwansanpo.com" + src
            return ' src="%s"' % src.replace('"', "&quot;")
        return ""

    def handle_starttag(self, tag, attrs):
        tag = RENAME.get(tag, tag)
        if tag in DROP_WITH_CONTENT:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        # table → ul 変換
        if tag == "table":
            self.in_table += 1
            self.out.append("<ul>")
            return
        if self.in_table:
            if tag == "tr":
                self.row_cells = []
            elif tag in ("td","th"):
                self.cell_buf = []
            return
        if tag == "figure":
            self.figure_depth += 1
        if tag == "span" and self.figure_depth:
            self.out.append("<figcaption>")
            self.span_as_figcaption.append(True)
            return
        if tag in BLOCK_KEEP or tag in INLINE_KEEP:
            if tag in ("img","br","hr"):
                self.out.append("<%s%s/>" % (tag, self._attrs(tag, attrs)))
            else:
                self.out.append("<%s%s>" % (tag, self._attrs(tag, attrs)))
        # その他(div,span,section...)は捨てて中身だけ通す

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in ("img","br","hr"):
            return  # 既に自己完結タグとして出力済み
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = RENAME.get(tag, tag)
        if tag in DROP_WITH_CONTENT:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "table":
            self.in_table = max(0, self.in_table - 1)
            self.out.append("</ul>")
            return
        if self.in_table:
            if tag in ("td","th") and self.cell_buf is not None:
                self.row_cells.append("".join(self.cell_buf).strip())
                self.cell_buf = None
            elif tag == "tr":
                cells = [c for c in self.row_cells if c]
                if cells:
                    self.out.append("<li>%s</li>" % "：".join(cells))
            return
        if tag == "span" and self.span_as_figcaption:
            self.span_as_figcaption.pop()
            self.out.append("</figcaption>")
            return
        if tag == "figure":
            self.figure_depth = max(0, self.figure_depth - 1)
        if tag in BLOCK_KEEP or tag in INLINE_KEEP:
            if tag not in ("img","br","hr"):
                self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.cell_buf is not None:
            self.cell_buf.append(data)
            return
        if self.in_table:
            return
        self.out.append(data)

    def handle_entityref(self, name):
        self.handle_data("&%s;" % name)

    def handle_charref(self, name):
        self.handle_data("&#%s;" % name)


def fetch(url):
    # macOSのpython.org版PythonはCA証明書未設定でSSLエラーになるため curl を使う
    r = subprocess.run(
        ["curl", "-sfL", "--max-time", "30", "-A", "Mozilla/5.0 (taiwansanpo feed generator)", url],
        capture_output=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: 記事の取得に失敗 (curl exit {r.returncode}): {url}")
    return r.stdout.decode("utf-8", "replace")


def extract_article(html_text):
    """記事ページから (タイトル, 本文モジュール群のHTML) を取り出す。"""
    m = re.search(r'<meta property="og:title" content="(.*?)"', html_text)
    title = m.group(1) if m else None
    if title:
        title = re.sub(r"\s*-\s*台湾さんぽ\s*$", "", title)
    seg_start = html_text.find('id="content_area"')
    seg_end = html_text.find("flexsocialbuttons", seg_start)
    seg = html_text[seg_start:seg_end if seg_end > 0 else None]
    # 記事本文 = j-htmlCode モジュール（自作HTMLウィジェット）の中身を連結
    bodies = []
    for m2 in re.finditer(r'<div[^>]*class="[^"]*j-htmlCode[^"]*"[^>]*>', seg):
        start = m2.end()
        depth = 1
        i = start
        while depth and i < len(seg):
            nxt_open = seg.find("<div", i)
            nxt_close = seg.find("</div>", i)
            if nxt_close < 0:
                break
            if 0 <= nxt_open < nxt_close:
                depth += 1
                i = nxt_open + 4
            else:
                depth -= 1
                i = nxt_close + 6
        bodies.append(seg[start:i - 6])
    return title, "\n".join(bodies)


def sanitize(raw_html):
    s = Sanitizer()
    s.feed(raw_html)
    out = "".join(s.out)
    out = re.sub(r"[ \t　]*\n[ \t　]*", "\n", out)   # 行頭行末の空白除去
    out = re.sub(r"[ \t]{2,}", " ", out)                      # 連続空白を1つに
    out = re.sub(r"<p>\s+", "<p>", out)
    out = re.sub(r"\s+</p>", "</p>", out)
    out = re.sub(r"<p>\s*</p>", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def rfc1123(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0900")


def cdata(text):
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def main():
    articles = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    state_path = ROOT / "feed_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    now = datetime.now(JST)
    if len(articles) > MAX_ITEMS:
        sys.exit(f"ERROR: 1フィード{MAX_ITEMS}本まで。articles.jsonが{len(articles)}本あります。分割してください。")

    items = []
    for art in articles:
        url = art["url"]
        html_text = fetch(url)
        title, raw = extract_article(html_text)
        title = art.get("title") or title
        body = sanitize(raw)
        if len(body) > MAX_BODY:
            sys.exit(f"ERROR: 本文が{len(body)}字でNordot上限{MAX_BODY}字を超過: {url}")
        if not body or not title:
            sys.exit(f"ERROR: 本文またはタイトルを抽出できません: {url}")
        digest = hashlib.sha256((title + body + art["publishedAt"]).encode()).hexdigest()
        st = state.get(url)
        if st and st.get("hash") == digest:
            fed_at = st["fedAt"]  # 変更なし → fedAt据え置き（再取得のたびに更新扱いさせない）
        else:
            fed_at = rfc1123(now)
            state[url] = {"fedAt": fed_at, "hash": digest}
        pub = datetime.strptime(art["publishedAt"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        if pub > now:
            sys.exit(f"ERROR: publishedAtが未来日付です: {url}")
        items.append({
            "guid": url, "sourceUrl": url, "fedAt": fed_at, "title": title,
            "body": body, "publishedAt": rfc1123(pub), "tags": art.get("tags", ""),
        })

    # fedAt 降順（同時刻はarticles.jsonの記載順を保持）
    items.sort(key=lambda x: datetime.strptime(x["fedAt"], "%a, %d %b %Y %H:%M:%S +0900"), reverse=True)

    xml = ['<?xml version="1.0" encoding="utf-8"?>',
           '<rss version="2.0" xmlns:nordot="https://www.nordot.jp/inputrss/strict/1.0/">',
           "<channel>",
           f"<nordot:unitId>{UNIT_ID}</nordot:unitId>"]
    for it in items:
        xml.append("<item>")
        xml.append(f"<nordot:guid>{it['guid']}</nordot:guid>")
        xml.append(f"<nordot:sourceUrl>{it['sourceUrl']}</nordot:sourceUrl>")
        xml.append(f"<nordot:fedAt>{it['fedAt']}</nordot:fedAt>")
        xml.append(f"<nordot:title>{cdata(it['title'])}</nordot:title>")
        xml.append("<nordot:status>public</nordot:status>")
        xml.append("<nordot:bodyType>nordot_html</nordot:bodyType>")
        xml.append(f"<nordot:body>{cdata(it['body'])}</nordot:body>")
        xml.append(f"<nordot:publishedAt>{it['publishedAt']}</nordot:publishedAt>")
        if it["tags"]:
            xml.append(f"<nordot:tags>{it['tags']}</nordot:tags>")
        xml.append("</item>")
    xml += ["</channel>", "</rss>", ""]

    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "feed.xml").write_text("\n".join(xml), encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(items)}記事 → docs/feed.xml ({sum(len(i['body']) for i in items)}字)")
    for it in items:
        print(f"  - [{len(it['body']):>6}字] fedAt={it['fedAt']}  {it['title'][:40]}")


if __name__ == "__main__":
    main()
