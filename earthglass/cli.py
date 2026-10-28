"""EarthGlass command-line interface."""

import typer

from .terminal_brand import PRODUCT, product_version, show_banner
from rich.console import Console
from rich.table import Table

from earthglass.layers import registry
from earthglass.providers import ProviderUnavailable
from earthglass.runtime import provider_manager

app = typer.Typer(
    help="EarthGlass: renderer-agnostic geospatial layer engine. By Blackfong.",
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
    table.add_column("ID", style="#83bfa9", no_wrap=True)
    table.add_column("Name", style="#83bfa9")
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
    table = Table(title="Provider and Cache Status")
    table.add_column("Provider", style="#83bfa9", no_wrap=True)
    table.add_column("State")
    table.add_column("Cached")
    table.add_column("Stale")
    table.add_column("Features")

    for status in provider_manager.statuses():
        table.add_row(
            str(status["name"]),
            str(status["state"]),
            "yes" if status["cache_available"] else "no",
            "yes" if status["cache_stale"] else "no",
            str(status["feature_count"]),
        )

    console.print(table)


@app.command()
def refresh(layer_id: str = typer.Argument(..., help="Layer to refresh.")) -> None:
    """Fetch, normalize, validate, and cache a layer now."""
    try:
        collection = provider_manager.refresh(layer_id)
    except (KeyError, ProviderUnavailable) as exc:
        console.print(f"[bold red]Refresh failed:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Refreshed {layer_id}:[/] {len(collection.features)} features "
        f"({collection.cache['status']})"
    )





def _show_version(value: bool):
    if value:
        typer.echo(f"{PRODUCT} {product_version()}")
        raise typer.Exit()


@app.callback()
def identity(
    version: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True, help="Print the installed product version."),
    banner: bool = typer.Option(False, "--banner", help="Show the product banner on stderr, including in scripts."),
    no_banner: bool = typer.Option(False, "--no-banner", help="Suppress the interactive startup banner."),
):
    if not no_banner:
        show_banner(force=banner)


if __name__ == "__main__":
    app()
