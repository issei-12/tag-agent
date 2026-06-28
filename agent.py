import json

from openai import OpenAI

import tools

MAX_TOOL_ITERATIONS = 10

SYSTEM_PROMPT = """あなたはDanbooru/e621タグの検索専門家。

ユーザーの自然言語入力（日本語可）から画像生成タグを探して返す。
プロンプトの生成は行わない。タグ探索のみ。

【検索手順】
1. ユーザーの入力から関連する英語キーワードを複数抽出
2. search_tags で各キーワードを1単語ずつ個別に検索
   重要: 1回のsearch_tags呼び出しに1単語のみ渡す
   例: "vaginal penetration" → search_tags("vaginal") と search_tags("penetration") の2回
3. 一般的なタグ（例: sex, kiss）と具体的なタグ（例: vaginal_penetration）の両方を含める
4. DBに実在するタグのみ返す

【出力形式】必ずこのJSONリスト形式で返す:
[{"name": "tag_name", "wiki": "日本語説明文"}, ...]

【説明文ルール】
- wiki_body（英語）があれば → 日本語に翻訳してwikiに入れる
- wiki_body が NULL → 知識から日本語説明を生成してwikiに入れる
- name はDBのバイト列そのまま（スペース/アンダースコア変換禁止）
- post_count が高いタグを優先
- 前置き・後書き不要。JSONリストのみ出力"""


def run(query: str, db_path: str = None) -> list[dict]:
    client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

    # Raises APIConnectionError if LM Studio is unreachable
    model_list = client.models.list()
    if not model_list.data:
        raise ConnectionError("LM Studio returned no models")
    model = model_list.data[0].id

    dispatch_kwargs = {"db_path": db_path} if db_path else {}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    iterations = 0

    while iterations < MAX_TOOL_ITERATIONS:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools.TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)

            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                    result = tools.dispatch(tc.function.name, args, **dispatch_kwargs)
                except Exception as ex:
                    result = json.dumps({"error": str(ex)}, ensure_ascii=False)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            iterations += 1
        else:
            content = choice.message.content or "[]"
            return _parse_result(content)

    # Cap reached: forced tool-less final completion
    messages.append({
        "role": "user",
        "content": "検索完了。収集したタグデータから関連性の高いものを選んでJSONリスト形式で出力。",
    })

    final = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    content = final.choices[0].message.content or "[]"
    return _parse_result(content)


def _parse_result(content: str) -> list[dict]:
    content = content.strip()

    # Try JSON array first
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(content[start : end + 1])
            if isinstance(data, list):
                return [
                    {"name": str(item["name"]), "wiki": str(item.get("wiki", ""))}
                    for item in data
                    if isinstance(item, dict) and "name" in item
                ]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: JSON object with "tags" key
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(content[start : end + 1])
            if isinstance(data, dict) and isinstance(data.get("tags"), list):
                return [
                    {"name": str(item["name"]), "wiki": str(item.get("wiki", ""))}
                    for item in data["tags"]
                    if isinstance(item, dict) and "name" in item
                ]
        except (json.JSONDecodeError, KeyError):
            pass

    return []
