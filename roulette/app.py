"""Local roulette API. Tests inject a mock transport; no database is used."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"


def normalize_base_url(value: str) -> str:
    """Only the selected user's local LM Studio, without redirects or proxies."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LM Studioのアドレスを確認してね。") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/v1"}
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("同じPCのLM Studioを指定してね。例：http://127.0.0.1:1234/v1")
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))


@dataclass(frozen=True)
class Settings:
    lm_base_url: str = DEFAULT_BASE_URL
    lm_api_token: str = ""
    generation_timeout_seconds: float = 30.0
    demo_only: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(ROOT / ".env", override=False)
        timeout = float(os.getenv("ROULETTE_GENERATION_TIMEOUT", "30"))
        if not 0 < timeout <= 120:
            raise ValueError("ROULETTE_GENERATION_TIMEOUTは0より大きく120以下に設定してね。")
        return cls(
            lm_base_url=normalize_base_url(os.getenv("LM_STUDIO_BASE_URL", DEFAULT_BASE_URL)),
            lm_api_token=os.getenv("LM_STUDIO_API_TOKEN", ""),
            generation_timeout_seconds=timeout,
            demo_only=os.getenv("ROULETTE_DEMO_ONLY", "false").lower() in {"true", "1", "yes"},
        )


class ModelsRequest(BaseModel):
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def local_address(cls, value: str | None) -> str | None:
        return normalize_base_url(value) if value else None


class GenerateRequest(ModelsRequest):
    model_config = ConfigDict(extra="forbid")
    feature_ids: list[str] = Field(min_length=1, max_length=20)
    mode: Literal["demo", "local"] = "demo"
    model: str = Field(default="", max_length=250)
    reasoning_off: bool = False
    minutes: Literal[15, 30, 60] = 30
    chaos: int = Field(default=1, ge=0, le=2)


class GeneratedIdea(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feature_id: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=40)
    constraint: str = Field(min_length=1, max_length=60)
    application: str = Field(min_length=1, max_length=100)


def fail(status: int, code: str, message: str, hint: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "hint": hint})


def catalog() -> list[dict]:
    return json.loads((ROOT / "data" / "features.json").read_text(encoding="utf-8"))


def prompt_for(idea: GeneratedIdea, feature: dict, minutes: int) -> str:
    return (
        f"{feature['name']}を使って、次の実験を実装して。\n\n"
        f"お題：{idea.topic}\n変な制約：{idea.constraint}\n"
        f"機能の使い方：{idea.application}\n作業時間の目安：{minutes}分\n\n"
        "まず利用条件と準備を確認し、時間内に触れる小さな完成形を目指して。\n"
        "日本語で操作できるようにして、プロジェクトのAGENTS.mdに従って進めて。\n"
        "検証は独立したテスト設定と練習用データで行い、実際に確認した内容を教えて。\n"
        f"公式情報：{feature['source_url']}"
    )


def result_for(idea: GeneratedIdea, feature: dict, minutes: int, source: str, model: str | None) -> dict:
    return {
        **idea.model_dump(),
        "feature": feature,
        "prompt": prompt_for(idea, feature, minutes),
        "source": source,
        "model": model,
    }


def demo_idea(features: list[dict], chaos: int) -> GeneratedIdea:
    feature = random.choice(features)
    sample = dict(feature["sample"])
    variations_path = ROOT / "data" / "demo_samples.json"
    if variations_path.exists():
        variations = json.loads(variations_path.read_text(encoding="utf-8"))
        candidates = variations.get(feature["id"], [])
        if candidates:
            sample = dict(random.choice(candidates))
    if chaos == 0:
        sample["constraint"] = "説明文を短くして、操作は3つ以内にする"
    elif chaos == 2:
        sample["constraint"] = random.choice([
            "すべての文言が魔王の指令口調。ただし操作は分かりやすく",
            "深海研究所が舞台。成功すると謎の研究員が祝福する",
            "かわいい顔で不穏なことを言う。結果は読みやすく",
            "架空の必殺技の名前をつける。説明は普通の日本語",
        ])
    return GeneratedIdea(feature_id=feature["id"], **sample)


def lm_http_error(response: httpx.Response) -> HTTPException:
    # Never echo upstream responses: they can contain tokens or prompt text.
    if response.status_code in {401, 403}:
        return fail(502, "lm_auth", "LM Studioの認証を確認してね。", ".envのLM_STUDIO_API_TOKENを確認してね。")
    if response.status_code == 404:
        return fail(502, "lm_model", "モデルまたはAPIが見つからなかった。", "LM Studioのモデルとサーバーのアドレスを確認してね。")
    return fail(502, "lm_response", "LM Studioが生成依頼を受け付けなかった。", "モデルをロードして、もう一度試してね。")


def new_client(settings: Settings, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {settings.lm_api_token}"} if settings.lm_api_token else {}
    return httpx.AsyncClient(
        headers=headers, transport=transport, trust_env=False, follow_redirects=False,
        timeout=httpx.Timeout(settings.generation_timeout_seconds, connect=3.0),
    )


async def generate_local(payload: GenerateRequest, features: list[dict], settings: Settings,
                         transport: httpx.AsyncBaseTransport | None) -> GeneratedIdea:
    schema = GeneratedIdea.model_json_schema()
    schema["properties"]["feature_id"]["enum"] = [f["id"] for f in features]
    tone = ["日常的で実用的", "少し奇妙で遊び心がある", "大胆で不穏、でも実装できる"][payload.chaos]
    messages = [
        {"role": "system", "content": (
            "あなたは短いハンズオンの実験企画者。日本語で1組の実験を考える。"
            "feature_idは必ず渡された候補から選ぶ。未知の機能・API・利用条件を創作しない。"
            "お題は40文字以下、変な制約は60文字以下、機能の使い方は100文字以下。"
            "有料接続や公開を必須にせず、指定時間内の最小実験にする。"
            "対象は自分で作る小さなローカルアプリ。機能の使い方は候補の例と利用条件に沿わせる。"
            "Markdown、解説、思考過程は書かず、指定されたJSONオブジェクトだけを返す。"
        )},
        {"role": "user", "content": (
            f"{payload.minutes}分で作る、{tone}実験を1組考えて。\n選べる機能：\n"
            + "\n".join(f"- {f['id']}: {f['name']}。{f['description']}"
                          f" 準備：{f['requirements']} 使い方の例：{f['sample']['application']}" for f in features)
            + "\n返答の形式（この4つのトップレベルキーだけ。他のキーは出さない）：\n"
            + json.dumps({"feature_id": "候補ID", "topic": "新しいお題",
                          "constraint": "新しい変な制約", "application": "選んだ機能をどう使うか"}, ensure_ascii=False)
            + f"\n抽選番号：{random.randrange(1_000_000)}。お題と制約は新しく創作して。"
        )},
    ]
    body = {
        "model": payload.model, "messages": messages, "temperature": 0.9,
        "max_tokens": 512, "stream": False,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "roulette_idea", "strict": True, "schema": schema,
        }},
    }
    base = payload.base_url or settings.lm_base_url
    async with new_client(settings, transport) as client:
        if payload.reasoning_off:
            # Only used when LM Studio advertises support for reasoning="off".
            parsed = urlsplit(base)
            endpoint = urlunsplit((parsed.scheme, parsed.netloc, "/api/v1/chat", "", ""))
            response = await client.post(endpoint, json={
                "model": payload.model, "system_prompt": messages[0]["content"],
                "input": messages[1]["content"], "reasoning": "off", "store": False,
                "stream": False, "temperature": 0.9, "max_output_tokens": 512,
            })
        else:
            response = await client.post(f"{base}/chat/completions", json=body)
            schema_unsupported = response.status_code in {400, 422} and any(
                word in response.text.lower() for word in ("response_format", "json_schema", "structured", "schema")
            )
            if schema_unsupported:
                # Some local models/engines do not support JSON Schema.
                body.pop("response_format")
                response = await client.post(f"{base}/chat/completions", json=body)
        if response.status_code != 200:
            raise lm_http_error(response)
        try:
            if payload.reasoning_off:
                content = "".join(item["content"] for item in response.json()["output"]
                                  if item.get("type") == "message")
            else:
                content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            content = content.strip()
            if content.startswith("```") and content.endswith("```"):
                content = "\n".join(content.splitlines()[1:-1]).strip()
            idea = GeneratedIdea.model_validate_json(content)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
            raise fail(502, "invalid_json", "モデルの回答を実験として読み取れなかった。",
                       "JSON出力に対応したモデルで再度試すか、デモで引いてね。") from None
        if idea.feature_id not in {f["id"] for f in features}:
            raise fail(502, "unknown_feature", "候補にない機能が返ってきた。", "結果は採用していないよ。もう一度試してね。")
        return idea


def create_app(settings: Settings | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Codex実験ルーレット", docs_url=None, redoc_url=None)
    generation_lock = asyncio.Lock()

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        # Keep this local server's generation endpoint out of cross-site requests.
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": {
                "code": "origin", "message": "アプリの画面から操作してね。", "hint": "",
            }})
        return await call_next(request)

    @app.get("/api/features")
    async def get_features():
        return {"features": catalog()}

    @app.get("/api/config")
    async def get_config():
        return {
            "lm_base_url": settings.lm_base_url,
            "auth_configured": bool(settings.lm_api_token),
            "generation_timeout_seconds": settings.generation_timeout_seconds,
            "demo_only": settings.demo_only,
        }

    @app.post("/api/models")
    async def get_models(payload: ModelsRequest):
        if settings.demo_only:
            raise fail(403, "demo_only", "今はデモ専用で起動しているよ。", "通常の起動に切り替えるとLM Studioへ接続できる。")
        base = payload.base_url or settings.lm_base_url
        try:
            async with new_client(settings, transport) as client:
                response = await asyncio.wait_for(client.get(f"{base}/models"), timeout=5)
                if response.status_code != 200:
                    raise lm_http_error(response)
                visible = response.json()["data"]
                if not isinstance(visible, list):
                    raise ValueError("model list")
                native: dict[str, dict] = {}
                try:
                    parsed = urlsplit(base)
                    native_url = urlunsplit((parsed.scheme, parsed.netloc, "/api/v1/models", "", ""))
                    detail = await asyncio.wait_for(client.get(native_url), timeout=2)
                    if detail.status_code == 200:
                        for item in detail.json().get("models", []):
                            native[item["key"]] = item
                            for instance in item.get("loaded_instances", []):
                                native[instance["id"]] = item
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
                    pass  # Older LM Studio: keep load status unknown.
                models = []
                for item in visible:
                    model_id = item.get("id")
                    if not isinstance(model_id, str):
                        continue
                    info = native.get(model_id)
                    if info and info.get("type") == "embedding":
                        continue
                    models.append({
                        "id": model_id,
                        "name": info.get("display_name", model_id) if info else model_id,
                        "loaded": bool(info.get("loaded_instances")) if info else None,
                        "type": info.get("type", "unknown") if info else "unknown",
                        "reasoning_off_available": bool(info and "off" in
                            ((info.get("capabilities") or {}).get("reasoning") or {}).get("allowed_options", [])),
                    })
                return {"models": models, "base_url": base,
                        "message": "接続できたよ。モデルを選んでね。" if models else "モデルが見つからなかった。LM Studioでモデルを準備してね。"}
        except (httpx.TimeoutException, TimeoutError):
            raise fail(504, "lm_timeout", "LM Studioの応答を待ちきれなかった。", "サーバーの状態を確認してね。") from None
        except httpx.HTTPError:
            raise fail(503, "lm_unreachable", "LM Studioにつながらなかった。", "Developerでサーバーを起動して、アドレスを確認してね。") from None
        except (ValueError, KeyError, TypeError):
            raise fail(502, "lm_models", "モデル一覧を読み取れなかった。", "LM Studioのサーバーを確認してね。") from None

    @app.post("/api/generate")
    async def generate(payload: GenerateRequest, request: Request):
        all_features = {f["id"]: f for f in catalog()}
        ids = list(dict.fromkeys(payload.feature_ids))
        if any(i not in all_features for i in ids):
            raise fail(422, "feature_selection", "使える機能を選び直してね。", "候補にない機能が指定されている。")
        features = [all_features[i] for i in ids]
        if payload.mode == "demo":
            idea = demo_idea(features, payload.chaos)
            return result_for(idea, all_features[idea.feature_id], payload.minutes, "demo", None)
        if settings.demo_only:
            raise fail(403, "demo_only", "今はデモ専用で起動しているよ。", "通常の起動に切り替えるとLM Studioへ接続できる。")
        if not payload.model.strip():
            raise fail(422, "model_required", "LM Studioのモデルを選んでね。", "先に接続確認をして、モデルを選ぼう。")
        if generation_lock.locked():
            raise fail(409, "busy", "ひとつ前の生成を処理中だよ。", "少し待ってからもう一度試してね。")
        async with generation_lock:
            work = asyncio.create_task(generate_local(payload, features, settings, transport))

            async def watch_disconnect():
                while not work.done():
                    if await request.is_disconnected():
                        work.cancel()
                        return
                    await asyncio.sleep(0.1)

            watcher = asyncio.create_task(watch_disconnect())
            try:
                idea = await asyncio.wait_for(work, settings.generation_timeout_seconds)
            except (httpx.TimeoutException, TimeoutError):
                raise fail(504, "generation_timeout", "生成の待ち時間を超えたよ。", "モデルのロード状態を確認するか、デモで引いてね。") from None
            except httpx.HTTPError:
                raise fail(503, "lm_unreachable", "LM Studioにつながらなかった。", "Developerでサーバーを起動してね。") from None
            except asyncio.CancelledError:
                raise fail(499, "cancelled", "生成の待機を終了した。", "") from None
            finally:
                watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher
                if not work.done():
                    work.cancel()
                    with suppress(asyncio.CancelledError):
                        await work
            return result_for(idea, all_features[idea.feature_id], payload.minutes, "local", payload.model)

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")
    return app


app = create_app()
