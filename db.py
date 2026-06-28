import sqlite3

DB_PATH = "tags.db"


def init_db(db_path: str = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tags (
                id         INTEGER,
                name       TEXT NOT NULL,
                category   INTEGER,
                post_count INTEGER,
                source     TEXT CHECK(source IN ('danbooru','e621')),
                wiki_body  TEXT,
                PRIMARY KEY (name, source)
            );
            CREATE INDEX IF NOT EXISTS idx_name  ON tags(name);
            CREATE INDEX IF NOT EXISTS idx_count ON tags(post_count DESC);
            CREATE INDEX IF NOT EXISTS idx_source ON tags(source);
        """)


def search_tags(
    query: str,
    source: str = "both",
    limit: int = 20,
    db_path: str = DB_PATH,
) -> list[dict]:
    # Tool-boundary normalization: space→underscore, lowercase
    q = query.replace(" ", "_").lower()
    # Escape underscore for LIKE (! is escape char)
    q_like = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")

    prefix_pat = q_like + "!_%"     # "red!_%" → starts with "red_"
    suffix_pat = "%!_" + q_like     # "%!_red" → ends with "_red"
    middle_pat = "%!_" + q_like + "!_%"  # "%!_red!_%" → contains "_red_"
    substr_pat = "%" + q_like + "%"  # "%red%" → any substring match

    source_clause = ""
    if source == "danbooru":
        source_clause = "AND source = 'danbooru'"
    elif source == "e621":
        source_clause = "AND source = 'e621'"

    sql = f"""
        SELECT name, post_count, source, wiki_body,
            CASE
                WHEN name = ? THEN 0
                WHEN (name LIKE ? ESCAPE '!') OR (name LIKE ? ESCAPE '!') THEN 1
                WHEN name LIKE ? ESCAPE '!' THEN 2
                ELSE 3
            END AS tier_rank
        FROM tags
        WHERE name LIKE ? ESCAPE '!'
        {source_clause}
    """
    params = [q, prefix_pat, suffix_pat, middle_pat, substr_pat]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    # Cross-source dedup: same name → prefer wiki_body IS NOT NULL, keep min tier_rank
    seen: dict[str, dict] = {}
    for row in rows:
        name = row["name"]
        d = dict(row)
        if name not in seen:
            seen[name] = d
        else:
            existing = seen[name]
            best_tier = min(existing["tier_rank"], d["tier_rank"])
            if d["wiki_body"] is not None and existing["wiki_body"] is None:
                seen[name] = {**d, "tier_rank": best_tier}
            else:
                seen[name] = {**existing, "tier_rank": best_tier}

    results = sorted(seen.values(), key=lambda r: (r["tier_rank"], -r["post_count"]))

    return [
        {
            "name": r["name"],
            "count": r["post_count"],
            "source": r["source"],
            "wiki": r["wiki_body"],
        }
        for r in results[:limit]
    ]


def get_tag_exact(
    name: str,
    source: str = "both",
    db_path: str = DB_PATH,
) -> dict | None:
    if source == "both":
        # Prefer wiki_body IS NOT NULL across sources
        sql = """
            SELECT name, post_count, source, wiki_body
            FROM tags
            WHERE name = ?
            ORDER BY (wiki_body IS NULL) ASC
            LIMIT 2
        """
        params = [name]
    else:
        sql = "SELECT name, post_count, source, wiki_body FROM tags WHERE name = ? AND source = ? LIMIT 1"
        params = [name, source]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return None

    row = rows[0]
    return {
        "name": row["name"],
        "count": row["post_count"],
        "source": row["source"],
        "wiki": row["wiki_body"],
    }
