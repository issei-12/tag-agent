from fastapi import FastAPI, HTTPException
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel

import agent

app = FastAPI(title="tag-agent")


class SearchRequest(BaseModel):
    query: str


@app.post("/tags/search")
async def search_tags(request: SearchRequest):
    try:
        tags = agent.run(request.query)
        return {"tags": tags}
    except (APIConnectionError, APITimeoutError, ConnectionError, OSError):
        raise HTTPException(status_code=500, detail="LM Studio connection failed")


@app.get("/health")
async def health():
    return {"status": "ok"}
