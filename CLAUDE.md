# tag-agent — CLAUDE.md

## プロジェクト概要

自然言語で意図を入力すると、LLMがTool callingでDanbooru/e621統合タグDBを検索し、
該当タグ一覧＋各タグの説明を返すタグ探索ツール。

**プロンプト生成は行わない。タグを探すことが目的。**

---

## 目的・ユースケース

```
ユーザー入力（日本語可）: 「赤髪エルフが正常位でセックスしているシーン」
         ↓
LLMが意図を解釈してDBを検索
         ↓
出力（フラットリスト＋説明）:
  red hair       - Hair that is red in color.
  pointy ears    - Ears that come to a point at the top.
  elf            - A fictional humanoid creature with pointed ears.
  missionary     - A sexual position where one partner lies on their back...
  vaginal penetration - Sexual act involving penetration of the vagina.
  ...
```

---

## アーキテクチャ

```
[Client]
   ↓ POST /tags/search
[FastAPI :8000]
   ↓ agent.run()
[agent.py] ←→ Tool calls ←→ [SQLite tags.db]
   ↓
[LM Studio :1234/v1 (OpenAI互換)]
   ↓
[タグリスト＋説明]
```

---

## ディレクトリ構造

```
tag-agent/
├── CLAUDE.md        ← このファイル
├── main.py          ← FastAPIエントリポイント
├── agent.py         ← LLM + Tool callingループ
├── tools.py         ← Tool定義 + dispatch
├── db.py            ← SQLiteアクセス
├── importer.py      ← タグ取得・インポートスクリプト
└── tags.db          ← 統合タグDB（初回実行後に生成）
```

---

## 環境

- **OS**: Windows（.bat推奨）
- **GPU**: RTX 5070 Ti / 16GB VRAM
- **LLM backend**: LM Studio（localhost:1234、OpenAI互換API）
- **画像生成モデル**: Anima（CircleStone Labs）※タグの利用先
- **Python**: 3.11+
- **DB**: SQLite（tags.db）

---

## 依存関係

```
fastapi
uvicorn
openai
requests
pydantic
```

```bat
pip install fastapi uvicorn openai requests pydantic
```

---

## DBスキーマ

```sql
CREATE TABLE tags (
    id         INTEGER,
    name       TEXT NOT NULL,
    category   INTEGER,
    post_count INTEGER,
    source     TEXT CHECK(source IN ('danbooru','e621')),
    wiki_body  TEXT,   -- e621 Wikiの説明文（NULLあり）
    PRIMARY KEY (name, source)
);

CREATE INDEX idx_name   ON tags(name);
CREATE INDEX idx_count  ON tags(post_count DESC);
CREATE INDEX idx_source ON tags(source);
```

---

## タグデータ取得方針

### タグ名・カウント
| ソース | 取得方法 | 説明 |
|--------|---------|------|
| Danbooru | API スクレイピング | rate limit: 500req/h（匿名） |
| e621 | 公式CSVダンプ | `https://e621.net/db_exports/` → `tags-YYYY-MM-DD.csv.gz` |

### 既製アーカイブ（推奨・最速）
```
https://github.com/DraconicDragon/dbr-e621-lists-archive
→ 毎月自動更新のCSVが置いてある（Danbooru + e621両方）
```

### Wiki説明文
- **e621のみ**取得（無料・NSFW完全対応）
- Danbooruはexplicit閲覧にGoldアカウント（有料）が必要なため不採用
- e621 Wiki API: `GET https://e621.net/wiki_pages.json?search[title]=TAG_NAME`
- 全タグ分は存在しない（メジャータグのみ）→ NULLで許容

---

## フィルタリング方針

```sql
-- 低頻度タグ除去
DELETE FROM tags WHERE post_count < 50;

-- e621固有構文除去（Animaが解釈できない）
DELETE FROM tags
WHERE source = 'e621'
AND (name LIKE 'lore:%' OR name LIKE 'species:%' OR name LIKE 'invalid:%');
```

---

## Tool定義

### search_tags
```python
# キーワードでタグを部分一致検索
# 引数:
#   query  : str  - 検索キーワード
#   source : str  - "danbooru" / "e621" / "both"（デフォルト: "both"）
#   limit  : int  - 最大件数（デフォルト: 20）
# 返値:
#   [{"name": str, "count": int, "source": str, "wiki": str|None}]
```

### get_tag_exact
```python
# タグの完全一致検索（存在確認）
# 引数:
#   name   : str
#   source : str - "danbooru" / "e621" / "both"
# 返値:
#   {"name": str, "count": int, "source": str, "wiki": str|None} | None
```

---

## LM Studio 設定

- エンドポイント: `http://localhost:1234/v1`
- api_key: `"lm-studio"`（任意の文字列でOK）
- モデル名: `/v1/models` で動的取得
- Tool calling対応モデル必須（Qwen2.5 / Llama3.1 等）

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
model = client.models.list().data[0].id
```

---

## System Prompt（agent.py）

```
あなたはDanbooru/e621タグの検索専門家。

ユーザーの自然言語入力（日本語可）からタグを探して返す。
プロンプトの生成は行わない。

手順:
1. ユーザーの入力を解析し、関連しそうなキーワードを複数抽出
2. search_tags で各キーワードを検索
3. 関連性の高いタグを選別して返す

出力形式（必ずこの形式）:
tag_name - 説明文（wiki_bodyがあればそれを使う、なければ簡潔に英語で補足）
tag_name - 説明文
...

ルール:
- DBに存在するタグのみ返す
- post_countが高いタグを優先
- 説明文は英語・簡潔に
- 余計な前置き・後書き不要
```

---

## API エンドポイント

### POST /tags/search
```json
Request:
{ "query": "赤髪エルフが正常位でセックスするシーン" }

Response:
{
  "tags": [
    { "name": "red hair",            "wiki": "Hair that is red in color." },
    { "name": "pointy ears",         "wiki": "Ears that taper to a point." },
    { "name": "missionary position", "wiki": "A sexual position where..." },
    { "name": "vaginal penetration", "wiki": "Sexual act involving..." }
  ]
}
```

### GET /health
```json
{ "status": "ok" }
```

---

## 起動

```bat
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## TODO

- [ ] importer.py: Danbooru APIスクレイピング実装
- [ ] importer.py: e621 CSVダンプ取込実装
- [ ] importer.py: e621 Wiki説明文取得実装
- [ ] tags.db 初期構築・フィルタリング実行
- [ ] db.py: search_tags / get_tag_exact 実装
- [ ] tools.py: Tool定義 + dispatch実装
- [ ] agent.py: Tool callingループ実装
- [ ] main.py: FastAPIエンドポイント実装
- [ ] LM Studio 動作確認

---

## 注意事項

- LM Studio は起動済みかつTool calling対応モデルがロード済みであること
- Danbooru APIはrate limit厳守（匿名: 500req/h → 1秒スリープ）
- e621 CSVダンプは手動ダウンロード推奨（自動DLはブロックされることあり）
- e621 Wiki取得もrate limit注意（1秒スリープ）
- tags.db 初回構築はDanbooru分で数時間かかる可能性あり