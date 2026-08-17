# taiwansanpo-nordot-feed

[台湾さんぽ](https://www.taiwansanpo.com/)（Jimdo Creator）の記事を
[Nordot（ノアドット）](https://nordot.app/)に配信するための Nordot Feed 生成リポジトリ。

## なぜ自前生成か

Jimdo純正RSS（`/rss/blog`）にはNordot非互換の問題があり（未来日付pubDateの混入・
本文が上限3万字超・直近18件のみ・`nordot:`必須要素なし）、過去に配信が失敗した経緯がある。
そのため**Jimdo RSSは使わず**、公開済み記事ページのHTMLから直接
[Nordot Feed仕様](https://nordotapp.notion.site/Nordot-Feed-2553915055aa80958288f769d8037754)
のXMLを生成し、GitHub Pagesでホストする。

## 使い方

1. `articles.json` に配信したい記事を並べる（1フィード20本まで／過去記事は `publishedAt` に元の公開日）
2. `python3 generate_feed.py` → `docs/feed.xml` が更新される
3. `git commit` して `git push` → GitHub Pages 経由で数分内に公開される
4. Nordotが10〜30分間隔でフィードを自動取得する

- `feed_state.json` は記事ごとの `fedAt`（入稿時刻）の台帳。本文・タイトル・公開日が
  変わった記事だけ `fedAt` が現在時刻に更新される（Nordotの更新検知の仕組みに合わせた挙動）。
  **手で編集しないこと。**
- フィードURL: `https://<user>.github.io/taiwansanpo-nordot-feed/feed.xml`
  （初回のみノアドット運営にこのURLの登録を依頼する必要がある）

## 過去記事のバックフィル

Nordot公式ガイドに従い、20本ずつ `articles.json` を入れ替えて
「生成→push→Nordotの取り込みを確認」を繰り返す。`fedAt` は自動で入稿ごとに新しくなる。

## 配信時の画像の注意

Nordotは本文`<img>`のURLから画像を自社DBに取り込み、提携メディアにも再配信する。
**引用ベースの画像（寺廟サイト等からの引用表示）は配信記事に含めないこと。**
Wikimedia Commons のCCライセンス画像（クレジット表記付き）または自前画像のみ使う。
