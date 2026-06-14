"""G5/#E: Production jobs must persist + link the adopted script_version_id.

The isolated worktree's conftest replaces TestClient with an inline ASGI client that
cannot drive the long-running digital-human HTTP endpoint (the existing
``tests/prompts`` job test fails the same way here), so these tests exercise the two
linking seams directly instead of through HTTP:

* ``jobs_runs._link_adopted_script`` — hydrates/validates the adopted ScriptVersion
  into the runtime repo at job creation so it is no longer orphaned;
* ``export_finished_video._resolve_script_version`` — REUSES the adopted
  ScriptVersion (preserving ``adopted_from_draft_id`` provenance) instead of
  fabricating a fresh orphan.

The script_version_id is stored on the job row inside the request payload (already a
contract field) and therefore surfaced verbatim by GET job detail; the persistence
round-trip through the JSONB request column is covered by
``tests/integration/test_sqlalchemy_workflow.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from apps.api.services import jobs_runs
from packages.core import contracts as c
from packages.core.storage.repository import Repository, new_id
from packages.production.pipeline._run_state import RunState
from packages.production.pipeline.nodes import export_finished_video


def _fake_request(repo: Repository, production_repo=None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                repository=repo,
                sqlalchemy_production_repository=production_repo,
            )
        )
    )


def _adopted_script(case_id: str = "case_demo") -> c.ScriptVersion:
    return c.ScriptVersion(
        id=new_id("script"),
        case_id=case_id,
        title="Adopted draft title",
        script="Adopted draft body from the Case Agent.",
        adopted_from_draft_id="draft_seed_001",
    )


def _request(case_id: str, script_version_id: str | None) -> c.DigitalHumanVideoRequest:
    return c.DigitalHumanVideoRequest(
        case_id=case_id,
        script="请求中携带的脚本正文。",
        title="Script-linked video",
        script_version_id=script_version_id,
        voice=c.VoiceOptions(voice_id="voice_sandbox"),
    )


# --- _link_adopted_script (job-creation seam) ---------------------------------


def test_link_adopted_script_keeps_in_memory_adopted_script() -> None:
    repo = Repository()
    script = _adopted_script()
    repo.scripts[script.id] = script
    payload = _request("case_demo", script.id)

    jobs_runs._link_adopted_script(_fake_request(repo), payload)

    # The adopted ScriptVersion (with provenance) stays available for the run.
    preserved = repo.scripts[script.id]
    assert preserved.adopted_from_draft_id == "draft_seed_001"
    assert preserved.title == "Adopted draft title"


def test_link_adopted_script_noop_without_id() -> None:
    repo = Repository()
    payload = _request("case_demo", None)
    jobs_runs._link_adopted_script(_fake_request(repo), payload)
    assert repo.scripts == {}


def test_link_adopted_script_drops_cross_case_script() -> None:
    repo = Repository()
    # An adopted script that belongs to a DIFFERENT case must never be relinked.
    foreign = _adopted_script(case_id="case_other")
    repo.scripts[foreign.id] = foreign
    payload = _request("case_demo", foreign.id)

    jobs_runs._link_adopted_script(_fake_request(repo), payload)

    assert foreign.id not in repo.scripts


def test_link_adopted_script_hydrates_from_production_repo() -> None:
    repo = Repository()
    script = _adopted_script()

    class _ProdRepo:
        def __init__(self) -> None:
            self.requested: list[str] = []

        def hydrate_adopted_script(self, repository, script_version_id):
            self.requested.append(script_version_id)
            if script_version_id == script.id:
                repository.scripts[script.id] = script
                return script
            return None

    prod = _ProdRepo()
    payload = _request("case_demo", script.id)

    jobs_runs._link_adopted_script(_fake_request(repo, production_repo=prod), payload)

    assert prod.requested == [script.id]
    assert repo.scripts[script.id].adopted_from_draft_id == "draft_seed_001"


# --- _resolve_script_version (run-completion seam) ----------------------------


def test_resolve_script_version_reuses_adopted_script() -> None:
    repo = Repository()
    script = _adopted_script()
    repo.scripts[script.id] = script
    state = RunState(request=_request("case_demo", script.id))

    resolved = export_finished_video._resolve_script_version(state, repo)

    # Same object reused -> provenance preserved, not orphaned.
    assert resolved is script
    assert resolved.adopted_from_draft_id == "draft_seed_001"


def test_resolve_script_version_mints_fresh_when_absent() -> None:
    repo = Repository()
    state = RunState(request=_request("case_demo", None))

    resolved = export_finished_video._resolve_script_version(state, repo)

    assert resolved.case_id == "case_demo"
    assert resolved.adopted_from_draft_id is None
    assert resolved.script == "请求中携带的脚本正文。"


def test_resolve_script_version_mints_under_requested_id_when_not_loaded() -> None:
    repo = Repository()
    state = RunState(request=_request("case_demo", "script_not_loaded"))

    resolved = export_finished_video._resolve_script_version(state, repo)

    # Falls back to minting under the requested id (DB-less / unknown id path).
    assert resolved.id == "script_not_loaded"
    assert resolved.adopted_from_draft_id is None


def test_resolve_script_version_ignores_cross_case_match() -> None:
    repo = Repository()
    foreign = _adopted_script(case_id="case_other")
    repo.scripts[foreign.id] = foreign
    state = RunState(request=_request("case_demo", foreign.id))

    resolved = export_finished_video._resolve_script_version(state, repo)

    # A same-id script from another case is not reused; a fresh row is minted.
    assert resolved is not foreign
    assert resolved.case_id == "case_demo"
