import asyncio
import shlex

import pytest

from jerico.tools.environments.base import ProcessExecutionResult
from jerico.tools.environments.docker import DockerEnvironment
from jerico.tools.environments.local import LocalEnvironment


@pytest.mark.asyncio
async def test_local_output_timeout_and_cleanup(tmp_path):
    runner = LocalEnvironment()
    result = await runner.execute_command("pwd", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == str(tmp_path)
    timeout = await runner.execute_command("sleep 10", timeout_s=0.02)
    assert timeout.timed_out
    assert not runner.processes
    await runner.cleanup()
    with pytest.raises(ValueError):
        await runner.execute_command("pwd", timeout_s=0)


@pytest.mark.asyncio
async def test_local_cancellation_kills_process_group():
    runner = LocalEnvironment()
    task = asyncio.create_task(runner.execute_command("sleep 10"))
    while not runner.processes:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runner.processes


@pytest.mark.asyncio
async def test_docker_has_no_network_mounts_or_privileges(tmp_path):
    class FakeRunner:
        async def execute_command(self, command, **kwargs):
            self.args = shlex.split(command)
            return ProcessExecutionResult(0, "ok", "")

        async def cleanup(self):
            self.cleaned = True

    fake = FakeRunner()
    environment = DockerEnvironment("test:pinned", fake)
    await environment.execute_command("id", env={"TEST": "value"})
    assert "--network=none" in fake.args
    assert "--read-only" in fake.args
    assert not any("docker.sock" in arg for arg in fake.args)
    assert fake.args[-3:] == ["/bin/sh", "-c", "id"]
    with pytest.raises(ValueError):
        await environment.execute_command("id", cwd=tmp_path)
    await environment.cleanup()
    assert fake.cleaned
