import json

import db

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_tags",
            "description": (
                "Search tags by keyword. "
                "IMPORTANT: pass ONE English word per call (1-token contract). "
                "Split compound concepts into separate calls. "
                "Example: 'vaginal penetration' → search_tags('vaginal') + search_tags('penetration'). "
                "Space-separated input is automatically normalized to underscore before matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Single English search token (e.g. 'red', 'hair', 'elf', 'missionary')",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["danbooru", "e621", "both"],
                        "default": "both",
                        "description": "Tag database to search",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "maximum": 100,
                        "description": "Maximum results to return",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tag_exact",
            "description": "Exact tag name lookup. Use to verify a tag exists before including in output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact tag name in underscore form (e.g. 'red_hair', 'vaginal_penetration')",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["danbooru", "e621", "both"],
                        "default": "both",
                    },
                },
                "required": ["name"],
            },
        },
    },
]

_VALID_SOURCES = {"danbooru", "e621", "both"}
_MAX_LIMIT = 100


def dispatch(tool_name: str, args: dict, db_path: str = db.DB_PATH) -> str:
    if tool_name == "search_tags":
        query = str(args.get("query", ""))
        source = str(args.get("source", "both"))
        if source not in _VALID_SOURCES:
            source = "both"
        limit = min(int(args.get("limit", 20)), _MAX_LIMIT)
        result = db.search_tags(query, source=source, limit=limit, db_path=db_path)
        return json.dumps(result, ensure_ascii=False)

    elif tool_name == "get_tag_exact":
        name = str(args.get("name", ""))
        source = str(args.get("source", "both"))
        if source not in _VALID_SOURCES:
            source = "both"
        result = db.get_tag_exact(name, source=source, db_path=db_path)
        return json.dumps(result, ensure_ascii=False)

    else:
        raise ValueError(f"Unknown tool: {tool_name!r}")
