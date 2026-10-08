"""Architecture fitness function: arch_check.py on synthetic package trees.

Covers: MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, MOD-07
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SPEC = "/architecture/modular-structure.md"
DOC = f'"""A module.\n\nSpec: {SPEC}\n"""\n'


def _load(tmp: Path):  # noqa: ANN202
    """Load arch_check.py pointed at `tmp`. Writes nothing, so it is safe on the real repo."""
    spec = importlib.util.spec_from_file_location("arch_check", REPO / "scripts" / "arch_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.ROOT, mod.PKG, mod.SPECS = tmp, tmp / "apps" / "api" / "voiceai", tmp / "specs"
    return mod


def _pkg(tmp: Path, files: dict[str, str]) -> None:
    """Write package-relative files, each with a valid Spec: docstring unless it brings its own."""
    for rel, body in files.items():
        p = tmp / "apps" / "api" / "voiceai" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body if body.lstrip().startswith('"""') else DOC + body, encoding="utf-8")
    stub = tmp / "specs" / SPEC.lstrip("/")  # the spec the fixtures above cite
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("# fixture spec\n", encoding="utf-8")


def _errors(tmp: Path) -> list[str]:
    mod = _load(tmp)
    rep = mod.Report()
    mod.check(rep)
    return rep.errors


def _ids(errors: list[str]) -> set[str]:
    return {e.split()[0] for e in errors}


# ---------------------------------------------------------------- MOD-01 contracts and cycles
def test_cross_module_import_must_use_contract(tmp_path):
    """Covers: MOD-01"""
    _pkg(tmp_path, {"modules/learning/service.py": "from voiceai.modules.agentcfg.repo import get_agent\n",
                    "modules/agentcfg/repo.py": "", "modules/agentcfg/contract.py": ""})
    errors = _errors(tmp_path)
    assert any("MOD-01" in e and "modules.agentcfg.contract" in e for e in errors)

    _pkg(tmp_path, {"modules/learning/service.py": "from voiceai.modules.agentcfg.contract import publish\n"})
    assert not _errors(tmp_path)


def test_module_internals_stay_reachable_within_the_module(tmp_path):
    """Covers: MOD-01"""
    _pkg(tmp_path, {"modules/learning/service.py": "from voiceai.modules.learning.repo import rows\n",
                    "modules/learning/repo.py": ""})
    assert not _errors(tmp_path)


def test_contract_cycle_fails(tmp_path):
    """Covers: MOD-01"""
    _pkg(tmp_path, {"modules/a/service.py": "from voiceai.modules.b.contract import x\n",
                    "modules/b/service.py": "from voiceai.modules.a.contract import y\n",
                    "modules/a/contract.py": "", "modules/b/contract.py": ""})
    errors = _errors(tmp_path)
    assert any("MOD-01" in e and "cycle" in e and "ports/" in e for e in errors)

    # the inversion: b stops naming a, so only a -> b remains
    _pkg(tmp_path, {"modules/b/service.py": "from voiceai.ports.postcall import PostCallAnalysis\n",
                    "ports/postcall.py": ""})
    assert not _errors(tmp_path)


# ---------------------------------------------------------------- MOD-02 adapters
def test_module_may_not_import_an_adapter(tmp_path):
    """Covers: MOD-02"""
    _pkg(tmp_path, {"modules/knowledge/search.py": "from voiceai.adapters.embeddings.hash import HashEmbedder\n",
                    "adapters/embeddings/hash.py": ""})
    errors = _errors(tmp_path)
    assert any("MOD-02" in e and "depend on a port" in e for e in errors)

    _pkg(tmp_path, {"modules/knowledge/search.py": "from voiceai.ports.embeddings import Embedder\n",
                    "ports/embeddings.py": ""})
    assert not _errors(tmp_path)


def test_composition_and_core_may_import_adapters(tmp_path):
    """Covers: MOD-02"""
    _pkg(tmp_path, {"composition/wiring.py": "from voiceai.adapters.llm.registry import client_for\n",
                    "core/embeddings.py": "from voiceai.adapters.embeddings.hash import HashEmbedder\n",
                    "adapters/llm/registry.py": "", "adapters/embeddings/hash.py": ""})
    assert not _errors(tmp_path)


def test_unlayered_code_may_not_import_adapters(tmp_path):
    """Covers: MOD-02"""
    _pkg(tmp_path, {"cli.py": "from voiceai.adapters.llm.registry import client_for\n",
                    "adapters/llm/registry.py": ""})
    assert any("MOD-02" in e and "may import adapters" in e for e in _errors(tmp_path))


# ---------------------------------------------------------------- MOD-03 ports are a leaf
def test_ports_import_nothing_internal_but_ports(tmp_path):
    """Covers: MOD-03"""
    _pkg(tmp_path, {"ports/llm.py": "from voiceai.core.config import get_settings\n", "core/config.py": ""})
    assert any("MOD-03" in e for e in _errors(tmp_path))

    _pkg(tmp_path, {"ports/llm.py": "from voiceai.ports.toolcaller import ToolCaller\n", "ports/toolcaller.py": ""})
    assert not _errors(tmp_path)


def test_ports_may_import_third_party_and_stdlib(tmp_path):
    """Covers: MOD-03"""
    _pkg(tmp_path, {"ports/llm.py": "import json\nfrom pydantic import BaseModel\n"})
    assert not _errors(tmp_path)


# ---------------------------------------------------------------- MOD-04 Pipecat confinement
def test_pipecat_is_confined_to_the_voice_module(tmp_path):
    """Covers: MOD-04"""
    _pkg(tmp_path, {"modules/conversation/session.py": "from pipecat.frames.frames import Frame\n"})
    assert any("MOD-04" in e and "pipecat" in e for e in _errors(tmp_path))

    _pkg(tmp_path, {"modules/conversation/session.py": "", "modules/voice/pipeline.py": "import pipecat\n"})
    assert not _errors(tmp_path)


def test_pipecat_confinement_holds_before_the_modules_split(tmp_path):
    """Covers: MOD-04"""
    _pkg(tmp_path, {"voice/pipeline.py": "import pipecat\n", "routes/calls.py": ""})
    assert not _errors(tmp_path)
    _pkg(tmp_path, {"routes/calls.py": "import pipecat\n"})
    assert any("MOD-04" in e for e in _errors(tmp_path))


# ---------------------------------------------------------------- MOD-05 traceability
def test_module_must_name_a_spec_that_exists(tmp_path):
    """Covers: MOD-05"""
    _pkg(tmp_path, {"core/db.py": '"""No spec here."""\n'})
    assert any("MOD-05" in e and "no `Spec:" in e for e in _errors(tmp_path))

    _pkg(tmp_path, {"core/db.py": '"""D.\n\nSpec: /architecture/does-not-exist.md\n"""\n'})
    assert any("MOD-05" in e and "does not exist" in e for e in _errors(tmp_path))

    _pkg(tmp_path, {"core/db.py": DOC})
    assert not _errors(tmp_path)


def test_empty_init_files_are_exempt(tmp_path):
    """Covers: MOD-05"""
    _pkg(tmp_path, {"core/db.py": DOC})
    (tmp_path / "apps" / "api" / "voiceai" / "core" / "__init__.py").write_text("", encoding="utf-8")
    assert not _errors(tmp_path)


# ---------------------------------------------------------------- MOD-06 the simulated system
def test_no_module_imports_the_simulated_business_system(tmp_path):
    """Covers: MOD-06"""
    _pkg(tmp_path, {"modules/learning/evaluate.py": "from voiceai.modules.businessmock.contract import members\n",
                    "modules/businessmock/contract.py": ""})
    errors = _errors(tmp_path)
    assert any("MOD-06" in e and "simulated" in e for e in errors)
    assert "MOD-01" not in _ids(errors)  # MOD-06 is the reason, not a contract violation

    _pkg(tmp_path, {"modules/learning/evaluate.py": "from voiceai.ports.callerdirectory import CallerDirectory\n",
                    "ports/callerdirectory.py": ""})
    assert not _errors(tmp_path)


def test_composition_may_wire_the_simulated_system(tmp_path):
    """Covers: MOD-06"""
    _pkg(tmp_path, {"composition/seed/loader.py": "from voiceai.modules.businessmock import data\n",
                    "modules/businessmock/data.py": ""})
    assert not _errors(tmp_path)


def test_the_simulated_system_may_use_its_own_internals(tmp_path):
    """Covers: MOD-06"""
    _pkg(tmp_path, {"modules/businessmock/api.py": "from voiceai.modules.businessmock import data\n",
                    "modules/businessmock/data.py": ""})
    assert not _errors(tmp_path)


# ---------------------------------------------------------------- MOD-07 tables
def test_relationship_in_tables_fails(tmp_path):
    """Covers: MOD-07"""
    _pkg(tmp_path, {"modules/conversation/tables.py": "from sqlalchemy.orm import relationship\nx = relationship('Agent')\n"})
    assert any("MOD-07" in e and "id column" in e for e in _errors(tmp_path))

    _pkg(tmp_path, {"modules/conversation/tables.py": "agent_id = mapped_column(ForeignKey('agents.id'))\n"})
    assert not _errors(tmp_path)


# ---------------------------------------------------------------- the real package
def test_real_package_satisfies_every_rule():
    """The backend package passes its own architecture rules."""
    mod = _load(REPO)
    rep = mod.Report()
    mod.check(rep)
    assert rep.errors == []
