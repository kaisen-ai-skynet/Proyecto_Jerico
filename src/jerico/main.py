import typer

from jerico.config import Settings, get_settings, token_configured

app = typer.Typer(help="Jericó — AI-OS de Kaisen AI")


def resolve_bind(host: str | None, port: int | None, settings: Settings) -> tuple[str, int]:
    return (settings.host if host is None else host, settings.port if port is None else port)


@app.command()
def serve(
    host: str | None = None,
    port: int | None = None,
    reload: bool = False,
) -> None:
    """Levanta la API de Jericó (FastAPI)."""
    from uvicorn import run as uvicorn_run

    settings = get_settings()
    if not token_configured(settings.api_token):
        typer.echo("JERICO_API_TOKEN no configurado. No arranco.", err=True)
        raise typer.Exit(code=1)
    bind_host, bind_port = resolve_bind(host, port, settings)
    uvicorn_run("jerico.api:app", host=bind_host, port=bind_port, reload=reload)


@app.command()
def ask(prompt: str, session_id: str = "default", verbose: bool = False) -> None:
    """Consulta directa por CLI. --verbose imprime nivel y modelo."""
    from jerico.llm_client import LLMClient
    from jerico.memory import memory
    from jerico.router import TokenRouter

    decision = TokenRouter().route(prompt)
    if verbose:
        typer.echo(f"[L{decision.level} {decision.model}]", err=True)
    if decision.answer is not None:
        answer = decision.answer
    else:
        answer = LLMClient().complete(
            prompt,
            level=decision.level,
            history=memory.context(session_id),
        )
    memory.append(session_id, "user", prompt)
    memory.append(session_id, "assistant", answer)
    typer.echo(answer)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
