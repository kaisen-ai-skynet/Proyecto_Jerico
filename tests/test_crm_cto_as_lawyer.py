"""El CTO usa los comandos del abogado SOLO con DRY_RUN activo, y cada uso queda auditado."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.team import DENIED
from test_crm_legal_bot import COM_TG, CTO_TG, LAW_TG, PDF, Env


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[object]:
    made: list[Env] = []

    def build(**kw: object) -> Env:
        env = Env(tmp_path, allowed=f"{LAW_TG},{CTO_TG},{COM_TG}", **kw)  # type: ignore[arg-type]
        made.append(env)
        return env

    yield build
    for env in made:
        env.close()


def _uses(env: Env) -> int:
    with env.db.read() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM crm_audit WHERE action='cto_lawyer_use'").fetchone()[
                0
            ]
        )


def _ref(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


def _contract_status(env: Env, lead_id: int) -> str:
    with env.db.read() as conn:
        row = conn.execute(
            "SELECT id FROM crm_packages WHERE lead_id=? ORDER BY id DESC LIMIT 1", (lead_id,)
        ).fetchone()
        return crepo.contract_for_package(conn, int(row["id"])).status  # type: ignore[union-attr]


def test_cto_runs_the_whole_lawyer_flow_in_dry_run_and_every_use_is_audited(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, CTO_TG, "/casos")
    assert _ref(lead_id) in env.texts(env.legal_tg, CTO_TG)[-1]
    env.say(env.legal, CTO_TG, f"/basejuridica {_ref(lead_id)}")
    env.say(env.legal, CTO_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload(PDF, tg_id=CTO_TG)
    assert _contract_status(env, lead_id) == "contract_uploaded"
    with env.db.read() as conn:
        assert repo.get_meta(conn, f"legal_basis_confirmed:{lead_id}") == str(env.cto.id)
    env.say(env.legal, CTO_TG, f"/devolver {_ref(lead_id)} falta una cláusula")
    assert _contract_status(env, lead_id) == "cancelled"
    assert _uses(env) == 5  # /casos, /basejuridica, /subircontrato, archivo y /devolver


def test_special_form_is_also_available_to_the_cto_in_dry_run(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, CTO_TG, f"/formaespecial {_ref(lead_id)}")
    assert _contract_status(env, lead_id) == "special_form" and _uses(env) == 1


def test_the_door_closes_when_dry_run_is_turned_off(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, CTO_TG, f"/subircontrato {_ref(lead_id)}")  # pendiente abierta en DRY_RUN
    before = _uses(env)
    object.__setattr__(env.ctx, "dry_run", False)  # se apaga DRY_RUN
    env.upload(PDF, tg_id=CTO_TG)  # el archivo ya no se acepta
    assert _contract_status(env, lead_id) == "package_sent"
    for command in (
        "/casos",
        f"/subircontrato {_ref(lead_id)}",
        f"/devolver {_ref(lead_id)} x",
        f"/formaespecial {_ref(lead_id)}",
        f"/basejuridica {_ref(lead_id)}",
    ):
        env.say(env.legal, CTO_TG, command)
    assert env.texts(env.legal_tg, CTO_TG).count(DENIED) >= 4
    assert _contract_status(env, lead_id) == "package_sent"
    assert _uses(env) == before  # nada nuevo auditado: ya no se sustituye el rol
    with env.db.read() as conn:
        assert repo.get_meta(conn, f"legal_basis_confirmed:{lead_id}") is None


def test_other_roles_never_get_the_lawyer_commands_even_in_dry_run(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, COM_TG, f"/subircontrato {_ref(lead_id)}")
    env.say(env.legal, COM_TG, "/casos")
    assert _contract_status(env, lead_id) == "package_sent" and _uses(env) == 0


def test_the_real_lawyer_is_unaffected_and_not_counted_as_cto_use(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload(PDF)
    assert _contract_status(env, lead_id) == "contract_uploaded" and _uses(env) == 0


def test_main_bot_registrations_follow_the_same_rule(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.main, CTO_TG, f"/formaespecial {_ref(lead_id)}")
    assert _contract_status(env, lead_id) == "special_form" and _uses(env) == 1
    object.__setattr__(env.ctx, "dry_run", False)
    env.say(env.main, CTO_TG, f"/devolver {_ref(lead_id)} x")
    assert _uses(env) == 1
