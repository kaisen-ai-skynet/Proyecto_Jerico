import typer
from uvicorn import run as uvicorn_run

app = typer.Typer(help="Jericó — AI-OS de Kaisen AI (v0)")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Levanta la API de Jericó (FastAPI)."""
    from jerico.config import get_settings

    settings = get_settings()
    uvicorn_run(
        "jerico.api:app", host=host or settings.host, port=port or settings.port, reload=reload
    )


@app.command()
def ask(prompt: str, session_id: str = "default") -> None:
    """Consulta directa por CLI: rutea L0/L1/L2 y responde."""
    from jerico.llm_client import LLMClient
    from jerico.router import TokenRouter

    decision = TokenRouter().route(prompt)
    if decision.answer is not None:
        typer.echo(decision.answer)
        return
    answer = LLMClient().complete(prompt, level=decision.level)
    typer.echo(answer)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
