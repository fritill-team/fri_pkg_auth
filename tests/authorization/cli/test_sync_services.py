"""pkg-auth-sync-services CLI smoke tests (fake repo via repo= injection)."""
from __future__ import annotations

import pytest

from pkg_auth.authorization import ServiceSpec
from pkg_auth.authorization.cli.sync_services import (
    build_arg_parser,
    load_services,
    main,
    run,
)

from tests.authorization.application.fakes import FakeServiceRepository

SAMPLE_SERVICES = [
    ServiceSpec.make("users", {"en": "Users"}, auto_provision=True),
    ServiceSpec.make("assessments", {"en": "Assessments"}, saas_available=True),
]


def test_parser_requires_services() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_load_services_resolves_module_attr() -> None:
    specs = load_services(f"{__name__}:SAMPLE_SERVICES")
    assert sorted(str(s.name) for s in specs) == ["assessments", "users"]


def test_load_services_rejects_bad_format() -> None:
    with pytest.raises(ValueError):
        load_services("no_colon")


async def test_run_syncs_via_injected_repo() -> None:
    repo = FakeServiceRepository()
    await repo.upsert_many([ServiceSpec.make("legacy")])

    parser = build_arg_parser()
    args = parser.parse_args(
        ["--services", f"{__name__}:SAMPLE_SERVICES", "--prune"]
    )
    result = await run(args, repo=repo)

    assert result.upserted == 2
    assert result.pruned == 1
    names = sorted(str(s.name) for s in await repo.list_all())
    assert names == ["assessments", "users"]


async def test_run_does_not_prune_without_flag() -> None:
    repo = FakeServiceRepository()
    await repo.upsert_many([ServiceSpec.make("legacy")])

    parser = build_arg_parser()
    args = parser.parse_args(["--services", f"{__name__}:SAMPLE_SERVICES"])
    result = await run(args, repo=repo)

    assert result.pruned == 0
    names = sorted(str(s.name) for s in await repo.list_all())
    assert names == ["assessments", "legacy", "users"]


async def test_run_dry_run_does_not_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = FakeServiceRepository()
    await repo.upsert_many([ServiceSpec.make("legacy")])

    parser = build_arg_parser()
    args = parser.parse_args(
        ["--services", f"{__name__}:SAMPLE_SERVICES", "--prune", "--dry-run"]
    )
    result = await run(args, repo=repo)

    assert result.dry_run is True and result.pruned == 1
    assert [str(s.name) for s in await repo.list_all()] == ["legacy"]
    assert "dry-run" in capsys.readouterr().out


def test_main_exit_non_zero_when_no_db_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACL_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["--services", f"{__name__}:SAMPLE_SERVICES"])
    assert exc.value.code not in (0, None)
