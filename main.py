from fastapi import FastAPI, HTTPException
from openai import APIError
from pydantic import BaseModel

import agent

app = FastAPI(title="tag-agent")


class SearchRequest(BaseModel):
    query: str


# sync def: FastAPI offloads to threadpool, preventing event-loop block during LLM calls
@app.post("/tags/search")
def search_tags(request: SearchRequest):
    try:
        tags = agent.run(request.query)
        return {"tags": tags}
    except (APIError, OSError):
        raise HTTPException(status_code=500, detail="LM Studio connection failed")


@app.get("/health")
async def health():
    return {"status": "ok"}
