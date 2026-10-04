"""API tests use an in-memory LM Studio double and never call a real model."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from roulette.app import Settings, create_app


BASE_URL = "http://127.0.0.1:1234/v1"
MODEL = "test-model"
EXPERIMENT = {
    "feature_id": "gpt61_sol",
    "topic": "深海研究所の集中タイマーを作る",
    "constraint": "残り1分で緊急モードになる",
    "application": "小さなタイマーをCodexで作り、見た目を調整する",
}


def generation_request(**overrides):
    return {
        "feature_ids": ["gpt61_sol"],
        "mode": "local",
        "model": MODEL,
        "base_url": BASE_URL,
        "minutes": 30,
        "chaos": 1,
        **overrides,
    }


def completion(content=None):
    if content is None:
        content = json.dumps(EXPERIMENT, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def isolated_client(handler=None, **settings):
    """A transport is always supplied, including for demo-only requests."""
    if handler is None:
        def handler(request):
            raise AssertionError(f"Unexpected LM Studio call: {request.method} {request.url}")

    isolated_settings = {
        "lm_base_url": BASE_URL,
        "lm_api_token": "",
        "generation_timeout_seconds": 30.0,
        "demo_only": False,
        **settings,
    }
    app = create_app(
        Settings(**isolated_settings),
        transport=httpx.MockTransport(handler),
    )
    return TestClient(app)


def assert_error(response, status):
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert isinstance(detail["code"], str) and detail["code"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["hint"], str) and detail["hint"]
    return detail


def test_demo_works_without_lm_studio_and_uses_selected_feature():
    with isolated_client() as client:
        response = client.post("/api/generate", json=generation_request(mode="demo", model=""))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == "demo"
        assert result["model"] is None
        assert result["feature_id"] == "gpt61_sol"
        assert result["feature"]["id"] == result["feature_id"]
        for field in ("topic", "constraint", "application", "prompt"):
            assert isinstance(result[field], str) and result[field].strip()
        assert result["topic"] in result["prompt"]
        assert result["constraint"] in result["prompt"]


def test_catalog_is_available_without_network_and_has_unique_ids():
    with isolated_client() as client:
        response = client.get("/api/features")
        assert response.status_code == 200
        features = response.json()["features"]
        ids = [feature["id"] for feature in features]
        assert "gpt61_sol" in ids
        assert "annotation_ext" in ids
        assert len(ids) == len(set(ids))
        assert all(feature["name"] for feature in features)


def test_config_reports_auth_presence_without_exposing_token():
    secret = "isolated-test-secret-do-not-return"
    with isolated_client(lm_api_token=secret, generation_timeout_seconds=12.5) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        assert response.json() == {
            "lm_base_url": BASE_URL,
            "auth_configured": True,
            "generation_timeout_seconds": 12.5,
            "demo_only": False,
        }
        assert secret not in response.text


@pytest.mark.parametrize("feature_ids", [[], ["unknown-feature"]])
def test_invalid_feature_selection_is_rejected_before_network(feature_ids):
    with isolated_client() as client:
        response = client.post("/api/generate", json=generation_request(feature_ids=feature_ids))
        assert response.status_code == 422


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com:1234/v1",
        "http://192.168.1.10:1234/v1",
        "http://127.0.0.1.example.com:1234/v1",
        "http://user:password@127.0.0.1:1234/v1",
        "file:///private/tmp/models",
    ],
)
def test_nonlocal_or_credentialed_urls_are_rejected_before_network(base_url):
    with isolated_client() as client:
        for endpoint, payload in (
            ("/api/models", {"base_url": base_url}),
            ("/api/generate", generation_request(base_url=base_url)),
        ):
            response = client.post(endpoint, json=payload)
            assert response.status_code == 422, response.text


@pytest.mark.parametrize("model", [None, "", "   "])
def test_local_generation_requires_a_model_before_network(model):
    with isolated_client() as client:
        response = client.post("/api/generate", json=generation_request(model=model))
        assert response.status_code == 422


def test_demo_only_setting_prevents_any_local_request():
    with isolated_client(demo_only=True) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 403)
        response = client.post("/api/generate", json=generation_request(mode="demo", model=""))
        assert response.status_code == 200


def test_models_distinguish_loaded_and_jit_candidates_and_filter_embeddings():
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [
                {"id": "test-model"}, {"id": "sleeping-model"}, {"id": "embed-model"},
            ]})
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": [
                {
                    "key": "publisher/test-model", "display_name": "Test model", "type": "llm",
                    "loaded_instances": [{"id": "test-model"}],
                    "capabilities": {"reasoning": {"allowed_options": ["off", "on"], "default": "on"}},
                },
                {
                    "key": "sleeping-model", "display_name": "Sleeping model", "type": "llm",
                    "loaded_instances": [],
                    "capabilities": {"reasoning": {"allowed_options": ["low", "high"], "default": "low"}},
                },
                {
                    "key": "embed-model", "display_name": "Embedding model", "type": "embedding",
                    "loaded_instances": [{"id": "embed-model"}],
                },
            ]})
        raise AssertionError(f"Unexpected path: {request.url.path}")

    with isolated_client(handler) as client:
        response = client.post("/api/models", json={"base_url": BASE_URL})
        assert response.status_code == 200, response.text
        models = {model["id"]: model for model in response.json()["models"]}
        assert set(models) == {"test-model", "sleeping-model"}
        assert models["test-model"]["name"] == "Test model"
        assert models["test-model"]["loaded"] is True
        assert models["test-model"]["reasoning_off_available"] is True
        assert models["sleeping-model"]["loaded"] is False
        assert models["sleeping-model"]["reasoning_off_available"] is False
        assert response.json()["base_url"] == BASE_URL
        assert requested_paths == ["/v1/models", "/api/v1/models"]


def test_models_do_not_claim_loaded_when_native_metadata_is_unavailable():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        if request.url.path == "/api/v1/models":
            return httpx.Response(404, json={"error": "Unsupported endpoint"})
        raise AssertionError(f"Unexpected path: {request.url.path}")

    with isolated_client(handler) as client:
        response = client.post("/api/models", json={"base_url": BASE_URL})
        assert response.status_code == 200, response.text
        assert response.json()["models"][0]["loaded"] is None
        assert response.json()["models"][0]["reasoning_off_available"] is False


def test_valid_generation_is_grounded_in_catalog_and_builds_copyable_prompt():
    seen = []

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["model"] == MODEL
        assert payload["response_format"]["type"] == "json_schema"
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["feature_id"]["enum"] == ["gpt61_sol"]
        return completion()

    with isolated_client(handler) as client:
        catalog = {item["id"]: item for item in client.get("/api/features").json()["features"]}
        response = client.post("/api/generate", json=generation_request())
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == "local"
        assert result["model"] == MODEL
        assert result["feature"] == catalog["gpt61_sol"]
        for field, value in EXPERIMENT.items():
            assert result[field] == value
        for field in ("topic", "constraint", "application"):
            assert result[field] in result["prompt"]
        assert len(seen) == 1


@pytest.mark.parametrize("content", [
    "not JSON",
    json.dumps({**EXPERIMENT, "feature_id": "imaginary-feature"}),
    json.dumps({**EXPERIMENT, "feature_id": "annotation_ext"}),
    json.dumps({**EXPERIMENT, "topic": ""}),
    json.dumps({**EXPERIMENT, "constraint": 123}),
])
def test_invalid_or_unselected_generation_is_not_adopted(content):
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return completion(content)

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 502)
        assert call_count == 1


def test_model_refusal_is_handled_as_an_error():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": None, "refusal": "I cannot generate this.",
        }}]})

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 502)


def test_schema_unsupported_retries_once_with_json_instruction():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {
                "message": "response_format json_schema is not supported by this model",
            }})
        assert payload.get("response_format", {}).get("type") != "json_schema"
        assert "json" in json.dumps(payload["messages"]).lower()
        return completion()

    with isolated_client(handler) as client:
        response = client.post("/api/generate", json=generation_request())
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "local"
        assert len(seen) == 2


def test_regular_bad_request_does_not_trigger_schema_fallback():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "Model not found"}})

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 502)
        assert len(calls) == 1


def test_fallback_does_not_reset_total_wait_budget():
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            await asyncio.sleep(0.15)
            return httpx.Response(400, json={"error": {
                "message": "response_format json_schema is not supported by this model",
            }})
        # Both attempts fit individually, but their combined wait exceeds the budget.
        await asyncio.sleep(0.15)
        return completion()

    with isolated_client(handler, generation_timeout_seconds=0.25) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 504)
        assert len(calls) == 2


def test_auth_rejection_is_not_retried_and_does_not_leak_token():
    secret = "isolated-auth-token-not-for-browser"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {secret}"
        return httpx.Response(401, json={"error": {"message": f"Rejected bearer {secret}"}})

    with isolated_client(handler, lm_api_token=secret) as client:
        response = client.post("/api/generate", json=generation_request())
        assert_error(response, 502)
        assert secret not in response.text
        assert len(calls) == 1


def test_server_connection_failure_has_actionable_error():
    def handler(request):
        raise httpx.ConnectError("Mock LM Studio is stopped", request=request)

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 503)


def test_http_timeout_has_actionable_error():
    def handler(request):
        raise httpx.ReadTimeout("Mock model did not reply", request=request)

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request()), 504)


def test_overlapping_requests_are_rejected_and_lock_is_released():
    started = threading.Event()
    release = threading.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return completion()

    with isolated_client(handler, generation_timeout_seconds=3.0) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(client.post, "/api/generate", json=generation_request())
            try:
                assert started.wait(timeout=1.5), "First request did not reach the mocked model"
                assert_error(client.post("/api/generate", json=generation_request()), 409)
            finally:
                release.set()
            assert first.result(timeout=2).status_code == 200
        assert len(calls) == 1
        # The completed request must not leave the app permanently busy.
        assert client.post("/api/generate", json=generation_request()).status_code == 200


def test_native_reasoning_off_returns_a_valid_experiment_without_storing_a_chat():
    seen = []

    def handler(request):
        assert request.url.path == "/api/v1/chat"
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["model"] == MODEL
        assert payload["reasoning"] == "off"
        assert payload["store"] is False
        assert payload["stream"] is False
        assert payload["max_output_tokens"] == 512
        assert payload["temperature"] == 0.9
        assert isinstance(payload["input"], str)
        assert "gpt61_sol" in payload["input"]
        assert isinstance(payload["system_prompt"], str)
        assert "json" in payload["system_prompt"].lower()
        assert "response_format" not in payload
        return httpx.Response(200, json={"output": [
            {"type": "message", "content": json.dumps(EXPERIMENT, ensure_ascii=False)},
        ]})

    with isolated_client(handler) as client:
        response = client.post("/api/generate", json=generation_request(reasoning_off=True))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == "local"
        assert result["model"] == MODEL
        assert result["feature_id"] == "gpt61_sol"
        assert result["feature"]["id"] == "gpt61_sol"
        for field, value in EXPERIMENT.items():
            assert result[field] == value
        assert len(seen) == 1


def test_native_reply_uses_message_output_and_accepts_json_code_fences():
    def handler(request):
        return httpx.Response(200, json={"output": [
            {"type": "reasoning", "content": "This text must not become the result."},
            {"type": "message", "content": "```json\n"},
            {"type": "message", "content": json.dumps(EXPERIMENT, ensure_ascii=False) + "\n```"},
        ]})

    with isolated_client(handler) as client:
        response = client.post("/api/generate", json=generation_request(reasoning_off=True))
        assert response.status_code == 200, response.text
        assert response.json()["topic"] == EXPERIMENT["topic"]
        assert "This text must not become" not in response.text


@pytest.mark.parametrize("output", [
    [],
    [{"type": "reasoning", "content": json.dumps(EXPERIMENT)}],
    [{"type": "message", "content": "not JSON"}],
    [{"type": "message", "content": None}],
    [{"type": "message", "content": json.dumps({**EXPERIMENT, "topic": "長" * 41})}],
    [{"type": "message", "content": json.dumps({**EXPERIMENT, "application": "長" * 101})}],
    [{"type": "message", "content": json.dumps({**EXPERIMENT, "feature_id": "unknown-native-feature"})}],
    [{"type": "message", "content": json.dumps({**EXPERIMENT, "feature_id": "annotation_ext"})}],
])
def test_native_invalid_or_unselected_output_is_not_adopted(output):
    calls = []

    def handler(request):
        assert request.url.path == "/api/v1/chat"
        calls.append(request)
        return httpx.Response(200, json={"output": output})

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request(reasoning_off=True)), 502)
        assert len(calls) == 1


def test_native_request_does_not_use_the_schema_fallback():
    calls = []

    def handler(request):
        assert request.url.path == "/api/v1/chat"
        calls.append(request)
        return httpx.Response(400, json={"error": {
            "message": "response_format json_schema is unsupported",
        }})

    with isolated_client(handler) as client:
        assert_error(client.post("/api/generate", json=generation_request(reasoning_off=True)), 502)
        assert len(calls) == 1


def test_native_auth_rejection_does_not_retry_or_return_a_secret():
    secret = "isolated-native-secret-not-for-browser"
    calls = []

    def handler(request):
        assert request.url.path == "/api/v1/chat"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": f"Rejected native token {secret}"}})

    with isolated_client(handler, lm_api_token=secret) as client:
        response = client.post("/api/generate", json=generation_request(reasoning_off=True))
        assert_error(response, 502)
        assert secret not in response.text
        assert len(calls) == 1
