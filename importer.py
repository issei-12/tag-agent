"""
Tag importer for Danbooru/e621 CSV dumps and wiki fetch.

Primary path: DraconicDragon/dbr-e621-lists-archive CSV
Fallback: Danbooru API (1 req/s, 500 req/h) + e621 official CSV dump

Usage:
  python importer.py <csv_path> <source>           # import tags CSV
  python importer.py --wikis-csv <wiki_pages.csv>  # bulk-load wiki bodies from e621 dump
  python importer.py --wikis [--limit N] [source]  # fetch wiki bodies via API
"""

import csv
import re
import sqlite3
import sys
import time

import requests

import db

WIKI_API = "https://e621.net/wiki_pages.json"
RATE_SLEEP = 1.0

_RE_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_RE_URL_LINK = re.compile(r'"([^"]+)":[^\s]+')
_RE_HEADING = re.compile(r"^h[1-6]\.\s*", re.MULTILINE)
_RE_BRACKET = re.compile(r"\[/?[^\]]*\]")


def normalize_dtext(text: str) -> str | None:
    if not text:
        return None
    # [[link]] / [[target|display]] → display or link text
    text = _RE_WIKI_LINK.sub(lambda m: m.group(2) if m.group(2) else m.group(1), text)
    # "text":url → text only
    text = _RE_URL_LINK.sub(r"\1", text)
    # h1.–h6. heading prefixes → strip
    text = _RE_HEADING.sub("", text)
    # ALL [tag] bracket constructs → remove
    text = _RE_BRACKET.sub("", text)
    text = text.strip()
    return text if text else None


def import_csv(path: str, source: str, db_path: str = db.DB_PATH) -> int:
    count = 0
    # Danbooru CSV has no header row; columns are name,category,post_count,aliases
    fieldnames = ["name", "category", "post_count", "aliases"] if source == "danbooru" else None
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, fieldnames=fieldnames)
            for row in reader:
                try:
                    name = row["name"].strip()
                    post_count = int(row.get("post_count", 0))
                    category = int(row.get("category", 0))
                    tag_id = int(row.get("id", 0))
                except (ValueError, KeyError):
                    continue
                # UPSERT: preserve existing wiki_body if already set
                conn.execute(
                    """
                    INSERT INTO tags (id, name, category, post_count, source, wiki_body)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(name, source) DO UPDATE SET
                        id         = excluded.id,
                        category   = excluded.category,
                        post_count = excluded.post_count
                    """,
                    [tag_id, name, category, post_count, source],
                )
                count += 1
        conn.commit()
    return count


def import_wiki_csv(path: str, db_path: str = db.DB_PATH) -> int:
    """Bulk-load e621 wiki bodies from wiki_pages CSV dump (faster than API)."""
    count = 0
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                title = row.get("title", "").strip()
                body = row.get("body", "")
                if not title or not body:
                    continue
                wiki = normalize_dtext(body)
                if not wiki:
                    continue
                conn.execute(
                    "UPDATE tags SET wiki_body = ? WHERE name = ? AND source = 'e621' AND wiki_body IS NULL",
                    [wiki, title],
                )
                count += 1
        conn.commit()
    return count


def filter_tags(db_path: str = db.DB_PATH) -> dict:
    with sqlite3.connect(db_path) as conn:
        cur1 = conn.execute("DELETE FROM tags WHERE post_count < 50")
        cur2 = conn.execute(
            "DELETE FROM tags WHERE source = 'e621' AND "
            "(name LIKE 'lore:%' OR name LIKE 'species:%' OR name LIKE 'invalid:%')"
        )
        conn.commit()
    return {
        "low_count_deleted": cur1.rowcount,
        "e621_prefix_deleted": cur2.rowcount,
    }


def fetch_wiki(tag_name: str, sleep: float = RATE_SLEEP) -> str | None:
    try:
        resp = requests.get(
            WIKI_API,
            params={"search[title]": tag_name},
            headers={"User-Agent": "tag-agent/1.0 (issei.ruka@icloud.com)"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                entry = data[0]
                if entry.get("title", "").lower() == tag_name.lower():
                    body = entry.get("body", "")
                    return normalize_dtext(body)
    except Exception:
        pass
    finally:
        time.sleep(sleep)
    return None


def update_wikis(
    source: str = "e621",
    limit: int | None = None,
    db_path: str = db.DB_PATH,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT name FROM tags WHERE source = ? AND wiki_body IS NULL ORDER BY post_count DESC"
        params = [source]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        tags = conn.execute(sql, params).fetchall()

    total = len(tags)
    print(f"Fetching wikis for {total} tags from {source}...")
    updated = 0
    for i, row in enumerate(tags):
        name = row["name"]
        wiki = fetch_wiki(name)
        if wiki:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE tags SET wiki_body = ? WHERE name = ? AND source = ?",
                    [wiki, name, source],
                )
                conn.commit()
            updated += 1
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{total} processed ({updated} updated)")

    print(f"Done. {updated}/{total} wiki bodies fetched.")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(1)

    db.init_db()

    if args[0] == "--wikis-csv":
        if len(args) < 2:
            print("Usage: python importer.py --wikis-csv <wiki_pages.csv>")
            sys.exit(1)
        n = import_wiki_csv(args[1])
        print(f"Wiki bodies loaded: {n}")
    elif args[0] == "--wikis":
        limit = None
        source = "e621"
        i = 1
        while i < len(args):
            if args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            else:
                source = args[i]
                i += 1
        update_wikis(source=source, limit=limit)
    else:
        if len(args) < 2:
            print("Usage: python importer.py <csv_path> <source>")
            sys.exit(1)
        csv_path, source = args[0], args[1]
        n = import_csv(csv_path, source)
        print(f"Imported {n} rows from {csv_path} (source={source})")
        stats = filter_tags()
        print(f"Filtered: {stats}")
