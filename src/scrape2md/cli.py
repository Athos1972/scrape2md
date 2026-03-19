from __future__ import annotations

from pathlib import Path

import typer

from scrape2md.config import load_config, merge_config, load_edge_config
from scrape2md.exporter import SiteExporter
from scrape2md.edge_scraper import EdgeHistoryScraper
from scrape2md.logging_utils import setup_logging
from scrape2md.models import CrawlConfig, EdgeConfig

app = typer.Typer(help="Crawl external websites into deterministic HTML/Markdown/asset exports.")


def _resolve_config(config_path: Path | None, start_url: str | None) -> CrawlConfig:
    config = load_config(config_path) if config_path else CrawlConfig(start_url=start_url or "")
    if start_url:
        config = merge_config(config, start_url=start_url)
    if not config.start_url:
        raise typer.BadParameter("Either provide URL argument or --config with start_url")
    return config


def _execute(config_path: Path | None, start_url: str | None) -> None:
    config = _resolve_config(config_path, start_url)
    setup_logging()
    manifest, export_root = SiteExporter(config).run()
    typer.echo(
        f"Done. pages={len(manifest.pages)} assets={len(manifest.assets)} errors={len(manifest.errors)} output={export_root}"
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    start_url: str | None = typer.Argument(None, help="Start URL"),
    config: Path | None = typer.Option(None, "--config", help="Path to TOML config"),
) -> None:
    if ctx.invoked_subcommand is None:
        _execute(config, start_url)


@app.command()
def edge(
    config: Path | None = typer.Option(None, "--config", help="Path to TOML config"),
) -> None:
    """Read Edge history and scrape recent URLs."""
    setup_logging()
    if not config:
        # Provide a default EdgeConfig if no config file is provided
        edge_config = EdgeConfig()
    else:
        edge_config = load_edge_config(config)
    
    EdgeHistoryScraper(edge_config).run()
    typer.echo("Edge history scraping done.")


@app.command()
def crawl(
    start_url: str | None = typer.Argument(None, help="Start URL"),
    config: Path | None = typer.Option(None, "--config", help="Path to TOML config"),
) -> None:
    _execute(config, start_url)


if __name__ == "__main__":
    app()
