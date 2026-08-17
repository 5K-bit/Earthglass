"""EarthGlass command-line interface."""

import typer
from rich.console import Console
from rich.table import Table

from earthglass.layers import registry

app = typer.Typer(
    help="EarthGlass: renderer-agnostic geospatial layer engine.",
    no_args_is_help=True,
)
cache_app = typer.Typer(help="Inspect EarthGlass cache state.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")

console = Console()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the server."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Run the EarthGlass API and demo web surface."""
    import uvicorn

    console.print(
        f"[bold green]Starting EarthGlass[/] on [cyan]http://{host}:{port}[/]"
    )
    uvicorn.run("earthglass.web.app:app", host=host, port=port, reload=reload)


@app.command()
def layers() -> None:
    """List registered geospatial layers."""
    table = Table(title="EarthGlass Layers")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="magenta")
    table.add_column("Category")
    table.add_column("Geometry")
    table.add_column("Provider")
    table.add_column("Enabled")

    for layer in registry.list():
        table.add_row(
            layer.id,
            layer.name,
            layer.category,
            layer.geometry,
            layer.provider,
            "yes" if layer.enabled else "no",
        )

    console.print(table)


@cache_app.command("status")
def cache_status() -> None:
    """Show the cache status for each layer."""
    console.print("[yellow]Provider caching is not enabled yet.[/]")

    table = Table(title="Cache Status")
    table.add_column("Layer", style="cyan", no_wrap=True)
    table.add_column("Cached")
    table.add_column("Entries")

    for layer in registry.list():
        table.add_row(layer.id, "no", "0")

    console.print(table)


if __name__ == "__main__":
    app()
