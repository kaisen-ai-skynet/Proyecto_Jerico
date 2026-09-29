"""Revisión adversarial del cliente LLM y del contrato read-only/confirm de las tools."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import ValidationError

from jerico.config import Settings
from jerico.llm_client import AsyncLLMClient, LLMError
from jerico.tools import REGISTRY, get_tool

# --- LLM client ---


class FakeCompletions:
    def __init__(self, response: Any = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def _response(*contents: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=c)) for c in contents]
    )


def _llm(completions: FakeCompletions) -> AsyncLLMClient:
    settings = Settings(
        llm_base_url="http://localhost/v1",
        llm_api_key="k",
        llm_model_l1="m1",
        llm_model_l2="m2",
        _env_file=None,  # type: ignore[call-arg]
    )
    client = AsyncLLMClient(settings)
    fake: Any = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._client_for = lambda level: (fake, settings.model_for_level(level))  # type: ignore[method-assign]
    return client


@pytest.mark.asyncio
async def test_prompt_igual_a_ultima_respuesta_no_se_descarta():
    comp = FakeCompletions(_response("ok"))
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "si"}]
    await _llm(comp).complete("si", history=history)
    assert comp.kwargs["messages"][-1] == {"role": "user", "content": "si"}


@pytest.mark.asyncio
async def test_prompt_ya_incluido_en_historial_no_se_duplica():
    comp = FakeCompletions(_response("ok"))
    await _llm(comp).complete("q", history=[{"role": "user", "content": "q"}])
    assert comp.kwargs["messages"] == [{"role": "user", "content": "q"}]


@pytest.mark.asyncio
async def test_historial_filtra_roles_invalidos_y_vacios():
    comp = FakeCompletions(_response("ok"))
    history = [
        {"role": "tool", "content": "inyectado"},
        {"role": "user", "content": ""},
        {"content": "sin rol"},
        {"role": "assistant", "content": "valido"},
    ]
    await _llm(comp).complete("p", history=history, system="sys")
    assert comp.kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "valido"},
        {"role": "user", "content": "p"},
    ]


@pytest.mark.asyncio
async def test_choices_vacio_es_llmerror():
    with pytest.raises(LLMError, match="sin choices"):
        await _llm(FakeCompletions(SimpleNamespace(choices=[]))).complete("p")


@pytest.mark.asyncio
async def test_content_none_devuelve_cadena_vacia():
    assert await _llm(FakeCompletions(_response(None))).complete("p") == ""


@pytest.mark.parametrize(
    "exc",
    [
        openai.APITimeoutError(request=httpx.Request("POST", "http://x")),
        openai.APIConnectionError(request=httpx.Request("POST", "http://x")),
        openai.RateLimitError(
            "rate", response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
            body=None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_errores_del_proveedor_se_envuelven(exc):
    with pytest.raises(LLMError) as info:
        await _llm(FakeCompletions(exc=exc)).complete("p")
    assert "k" not in str(info.value).split()  # la API key nunca viaja en el mensaje


@pytest.mark.parametrize("level", [0, -1])
@pytest.mark.asyncio
async def test_nivel_0_nunca_llama_al_proveedor(level):
    comp = FakeCompletions(_response("x"))
    with pytest.raises(ValueError):
        await _llm(comp).complete("p", level=level)
    assert comp.kwargs == {}


@pytest.mark.asyncio
async def test_nivel_selecciona_modelo():
    comp = FakeCompletions(_response("x"))
    await _llm(comp).complete("p", level=2)
    assert comp.kwargs["model"] == "m2"


def test_cliente_openai_se_reutiliza_por_endpoint():
    settings = Settings(llm_base_url="http://localhost/v1", llm_api_key="k", _env_file=None)  # type: ignore[call-arg]
    llm = AsyncLLMClient(settings)
    c1, _ = llm._client_for(1)
    c2, _ = llm._client_for(2)
    assert c1 is c2


# --- Tools ---


WRITE_TOOLS = [name for name, tool in REGISTRY.items() if not tool.readonly]


@pytest.mark.parametrize("name", WRITE_TOOLS)
@pytest.mark.parametrize("confirm", ["false", "true", 1, "yes", [True], object()])
def test_confirm_debe_ser_true_estricto(name, confirm):
    result = get_tool(name).run(confirm=confirm)  # type: ignore[union-attr, arg-type]
    assert result["ok"] is False
    assert result["error"] == "CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("name", list(REGISTRY))
def test_tools_del_registro_son_inmutables(name):
    # Instancia nueva de la misma clase: si el test falla, no contamina el REGISTRY.
    tool = type(REGISTRY[name])()
    with pytest.raises(ValidationError):
        tool.readonly = not tool.readonly
    with pytest.raises(ValidationError):
        tool.name = "otro"


def _audit_entries(path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_kwargs_no_pueden_falsificar_el_audit(audit_log_aislado):
    get_tool("youtrack_create_issue").run(  # type: ignore[union-attr]
        confirm=True, tool="youtrack_list_issues", ts="1999", status="blocked"
    )
    entry = _audit_entries(audit_log_aislado)[-1]
    assert entry["tool"] == "youtrack_create_issue"
    assert entry["status"] == "executed"
    assert entry["ts"] != "1999"
    assert entry["args"] == {"tool": "youtrack_list_issues", "ts": "1999", "status": "blocked"}


def test_intento_de_escritura_bloqueado_queda_auditado(audit_log_aislado):
    get_tool("docker_restart_container").run(confirm="false", container="db")  # type: ignore[union-attr, arg-type]
    entry = _audit_entries(audit_log_aislado)[-1]
    assert entry["tool"] == "docker_restart_container"
    assert entry["status"] == "blocked"
    assert entry["confirm"] == "false"


def test_audit_con_args_no_serializables(audit_log_aislado):
    get_tool("notion_query_db").run(db_id=object())  # type: ignore[union-attr]
    assert _audit_entries(audit_log_aislado)[-1]["tool"] == "notion_query_db"


def test_audit_no_escribible_no_rompe_la_tool(monkeypatch, tmp_path):
    blocker = tmp_path / "archivo"
    blocker.write_text("x")
    monkeypatch.setattr("jerico.tools.base.AUDIT_LOG", blocker / "audit.log")
    assert get_tool("docker_list_containers").run()["ok"] is True  # type: ignore[union-attr]


def test_tool_de_lectura_con_kwarg_desconocido_falla_cerrado():
    with pytest.raises(TypeError):
        get_tool("docker_list_containers").run(rm_rf=True)  # type: ignore[union-attr]
