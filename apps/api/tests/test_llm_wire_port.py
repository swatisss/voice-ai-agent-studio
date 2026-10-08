"""The LLM wire port: a provider is configuration, not code.

Covers: LG-12, LG-13, LG-14, LG-15
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from voiceai.adapters.llm import registry
from voiceai.adapters.llm import openai_compatible as wire
from voiceai.core.config import Settings
from voiceai.core.llm import gateway as gw
from voiceai.ports.llm import ChatClient, ChatResult, ProviderConfig, Usage

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "apps" / "api" / "voiceai"
ROLES = ("realtime", "analysis", "drafting", "simulator", "judge", "turn")


def _yaml(tmp_path: Path, providers: dict, models: dict, roles: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"providers": providers, "models": models, "roles": roles}), encoding="utf-8")
    return path


def _gateway(monkeypatch, config: Path, **keys: str) -> gw.Gateway:  # noqa: ANN001
    monkeypatch.setattr(gw, "fake_active", lambda: False)
    monkeypatch.setattr(gw, "get_settings", lambda: Settings(_env_file=None, **keys))
    for role in ROLES:
        monkeypatch.delenv(f"LLM_ROLE_{role.upper()}", raising=False)
    return gw.Gateway(config)


# ---------------------------------------------------------------- a new wire, with no core change
@pytest.fixture
def pretend_wire(monkeypatch, tmp_path):  # noqa: ANN001, ANN201
    """Register an adapter for a wire that does not speak the OpenAI protocol at all.

    It is written into a throwaway module and resolved through the registry exactly as a real one
    would be, so this proves the seam without adding a dependency.
    """
    seen: list[dict] = []

    class PretendClient:
        def __init__(self, cfg: ProviderConfig) -> None:
            self.cfg = cfg

        async def stream(self, model, messages, tools, params):  # noqa: ANN001, ANN202
            seen.append({"model": model, "base_url": self.cfg.base_url, "api_key": self.cfg.api_key,
                         "params": params, "options": dict(self.cfg.options)})
            yield {"type": "text", "text": "ahoy"}
            yield {"type": "done", "result": ChatResult(text="ahoy", usage=Usage(30, 7))}

        async def complete_json(self, model, messages, schema, params):  # noqa: ANN001, ANN202
            seen.append({"model": model, "schema": schema})
            return '{"ok": true}', Usage(3, 1)

        async def aclose(self) -> None:
            return None

    module = type(sys)("voiceai.adapters.llm.pretend")
    module.build = PretendClient
    monkeypatch.setitem(sys.modules, "voiceai.adapters.llm.pretend", module)
    return seen


async def test_a_new_provider_is_yaml_plus_an_env_var(monkeypatch, tmp_path, pretend_wire):
    """Covers: LG-12"""
    monkeypatch.setenv("PRETEND_API_KEY", "pk-live")
    config = _yaml(
        tmp_path,
        providers={"pretend": {"wire": "pretend", "base_url": "https://pretend.example/v1",
                               "api_key_env": "PRETEND_API_KEY", "options": {"dialect": "nautical"}}},
        models={"pretend:parrot-1": {"input": 1.0, "output": 2.0}},
        roles={"realtime": {"model": "pretend:parrot-1", "params": {"temperature": 0.3}}},
    )
    g = _gateway(monkeypatch, config)
    assert g.provider_configured("pretend")

    events = [e async for e in g.stream_chat("realtime", [{"role": "user", "content": "hi"}])]
    assert [e["text"] for e in events if e["type"] == "text"] == ["ahoy"]
    result = events[-1]["result"]
    assert result.model_ref == "pretend:parrot-1"
    assert result.usage.cost_usd == pytest.approx(30 * 1.0 / 1e6 + 7 * 2.0 / 1e6)  # priced by the gateway

    call = pretend_wire[0]
    assert call["model"] == "parrot-1" and call["base_url"] == "https://pretend.example/v1"
    assert call["api_key"] == "pk-live" and call["params"] == {"temperature": 0.3}
    assert call["options"]["dialect"] == "nautical"  # wire-specific config reaches the wire untouched


def test_adding_a_provider_names_no_python_file(monkeypatch, tmp_path, pretend_wire):
    """Covers: LG-12"""
    monkeypatch.setenv("PRETEND_API_KEY", "pk-live")
    config = _yaml(
        tmp_path,
        providers={"pretend": {"wire": "pretend", "base_url": "https://pretend.example/v1", "api_key_env": "PRETEND_API_KEY"}},
        models={"pretend:parrot-1": {"input": 1.0, "output": 2.0}},
        roles={"realtime": {"model": "pretend:parrot-1"}},
    )
    g = _gateway(monkeypatch, config)
    assert g.api_key("pretend") == "pk-live"  # resolved from the declared api_key_env, not a field
    assert "pretend" not in (PKG / "core" / "config.py").read_text(encoding="utf-8")
    assert "pretend" not in (PKG / "core" / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert g.selectable() == ["pretend:parrot-1"]


def test_wire_defaults_to_openai_so_existing_config_keeps_working(monkeypatch, tmp_path):
    """Covers: LG-12"""
    monkeypatch.setenv("LEGACY_API_KEY", "lk")
    config = _yaml(
        tmp_path,
        providers={"legacy": {"base_url": "https://legacy.example/v1", "api_key_env": "LEGACY_API_KEY", "stream_usage": True}},
        models={"legacy:m": {"input": 1.0, "output": 1.0}},
        roles={"realtime": {"model": "legacy:m"}},
    )
    g = _gateway(monkeypatch, config)
    cfg = g._provider_cfg("legacy")
    assert cfg.wire == registry.DEFAULT_WIRE
    assert cfg.options["stream_usage"] is True  # the pre-`options` spelling still reaches the wire
    assert isinstance(g._client("legacy"), wire.OpenAICompatibleClient)
    assert isinstance(g._client("legacy"), ChatClient)


# ---------------------------------------------------------------- /healthz is derived
async def test_healthz_providers_come_from_models_yaml(client, monkeypatch, tmp_path, pretend_wire):
    """Covers: LG-13"""
    monkeypatch.setenv("PRETEND_API_KEY", "pk-live")
    monkeypatch.delenv("PARROT_API_KEY", raising=False)
    config = _yaml(
        tmp_path,
        providers={"pretend": {"wire": "pretend", "base_url": "https://pretend.example/v1", "api_key_env": "PRETEND_API_KEY"},
                   "parrot": {"wire": "pretend", "base_url": "https://parrot.example/v1", "api_key_env": "PARROT_API_KEY"}},
        models={"pretend:parrot-1": {"input": 1.0, "output": 2.0}},
        roles={"realtime": {"model": "pretend:parrot-1"}},
    )
    g = _gateway(monkeypatch, config)
    monkeypatch.setattr(gw, "_gateway", g)
    providers = (await client.get("/healthz")).json()["providers"]
    assert providers == {"pretend": True, "parrot": False, "deepgram": False}


def test_real_config_declares_a_wire_for_every_provider():
    """Covers: LG-13"""
    cfg = yaml.safe_load((REPO / "apps" / "api" / "config" / "models.yaml").read_text(encoding="utf-8"))
    for name, p in cfg["providers"].items():
        assert p.get("wire"), f"{name} declares no wire"
        assert registry.factory(p["wire"]), f"{name} names a wire with no adapter"
        assert p.get("api_key_env"), f"{name} declares no api_key_env"


# ---------------------------------------------------------------- an unusable wire is skipped
async def test_unknown_wire_is_skipped_like_a_missing_key(monkeypatch, tmp_path, pretend_wire):
    """Covers: LG-14"""
    monkeypatch.setenv("BROKEN_API_KEY", "bk")
    monkeypatch.setenv("PRETEND_API_KEY", "pk-live")
    config = _yaml(
        tmp_path,
        providers={"broken": {"wire": "no_such_wire", "base_url": "https://b.example/v1", "api_key_env": "BROKEN_API_KEY"},
                   "pretend": {"wire": "pretend", "base_url": "https://pretend.example/v1", "api_key_env": "PRETEND_API_KEY"}},
        models={"broken:m": {"input": 1.0, "output": 1.0}, "pretend:parrot-1": {"input": 1.0, "output": 2.0}},
        roles={"realtime": {"model": "broken:m", "fallback": ["pretend:parrot-1"]}},
    )
    g = _gateway(monkeypatch, config)
    events = [e async for e in g.stream_chat("realtime", [{"role": "user", "content": "x"}])]
    assert events[-1]["result"].model_ref == "pretend:parrot-1"  # the next ref answered

    with pytest.raises(registry.UnknownWire, match="no adapter for wire"):
        registry.factory("no_such_wire")
    with pytest.raises(registry.UnknownWire, match="invalid wire name"):
        registry.factory("../../etc/passwd")  # models.yaml cannot name an arbitrary module


def test_importing_the_app_loads_no_wire_adapter_eagerly():
    """Covers: LG-14"""
    code = textwrap.dedent(
        """
        import sys
        import voiceai.core.llm.gateway  # noqa: F401
        loaded = [m for m in sys.modules if m.startswith("voiceai.adapters.llm.") and not m.endswith("registry")]
        print(",".join(sorted(loaded)))
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO / "apps" / "api")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""  # a wire module is imported only when a provider needs it


# ---------------------------------------------------------------- per-provider quirks are data
def test_usage_quirk_is_declared_in_yaml_not_coded(monkeypatch):
    """Covers: LG-15"""
    from types import SimpleNamespace

    def chunk(**kw):  # noqa: ANN003, ANN202
        return SimpleNamespace(choices=[], **kw)

    quirky = wire.OpenAICompatibleClient.__new__(wire.OpenAICompatibleClient)
    quirky.cfg = ProviderConfig(name="q", wire="openai", base_url="u", api_key="k", options={"usage_extra_key": "x_groq"})
    plain = wire.OpenAICompatibleClient.__new__(wire.OpenAICompatibleClient)
    plain.cfg = ProviderConfig(name="p", wire="openai", base_url="u", api_key="k")

    vendor = chunk(usage=None, model_extra={"x_groq": {"usage": {"prompt_tokens": 11, "completion_tokens": 3}}})
    assert quirky._usage_from(vendor) == {"prompt_tokens": 11, "completion_tokens": 3}
    assert plain._usage_from(vendor) is None  # without the declaration the extension is ignored

    standard = chunk(usage={"prompt_tokens": 4, "completion_tokens": 1}, model_extra=None)
    assert quirky._usage_from(standard) == {"prompt_tokens": 4, "completion_tokens": 1}  # the standard field wins

    assert "x_groq" not in (PKG / "core" / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert "groq" not in (PKG / "composition" / "ops_api.py").read_text(encoding="utf-8")


async def test_gateway_estimates_usage_when_the_wire_reports_none(monkeypatch, tmp_path, pretend_wire):
    """Covers: LG-15"""
    monkeypatch.setenv("SILENT_API_KEY", "sk")

    class Silent:
        def __init__(self, cfg: ProviderConfig) -> None:
            self.cfg = cfg

        async def stream(self, model, messages, tools, params):  # noqa: ANN001, ANN202
            yield {"type": "text", "text": "x" * 40}
            yield {"type": "done", "result": ChatResult(text="x" * 40)}  # usage left at zero

        async def complete_json(self, model, messages, schema, params):  # noqa: ANN001, ANN202
            raise NotImplementedError

        async def aclose(self) -> None:
            return None

    module = type(sys)("voiceai.adapters.llm.silent")
    module.build = Silent
    monkeypatch.setitem(sys.modules, "voiceai.adapters.llm.silent", module)
    config = _yaml(
        tmp_path,
        providers={"silent": {"wire": "silent", "base_url": "u", "api_key_env": "SILENT_API_KEY"}},
        models={"silent:m": {"input": 1.0, "output": 1.0}},
        roles={"realtime": {"model": "silent:m"}},
    )
    g = _gateway(monkeypatch, config)
    events = [e async for e in g.stream_chat("realtime", [{"role": "user", "content": "y" * 80}])]
    usage = events[-1]["result"].usage
    assert (usage.input_tokens, usage.output_tokens) == (80 // 4, 40 // 4)  # characters / 4
    assert usage.cost_usd == pytest.approx(20 / 1e6 + 10 / 1e6)
