"""Semantica CLI: `semantica transpile <model.yaml> --target <target> ...`"""

from pathlib import Path

import click

from semantica.dispatch import TARGETS
from semantica.dispatch import transpile as dispatch_transpile
from semantica.parser import load_osi_document
from semantica.resolved_model import ResolvedModel


@click.group()
def main() -> None:
    """Semantica: transpile OSI semantic models to warehouse SQL and BI/AI formats."""


@main.command()
@click.argument("model_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--target", type=click.Choice(TARGETS), required=True)
@click.option("--metric", help="Metric name (required for SQL targets)")
@click.option(
    "--group-by",
    multiple=True,
    metavar="DATASET.FIELD",
    help="Field to group by, e.g. item.i_category (SQL targets only, repeatable)",
)
@click.option("--out", type=click.Path(dir_okay=False), help="Write output to a file instead of stdout")
def transpile(model_path: str, target: str, metric: str | None, group_by: tuple[str, ...], out: str | None) -> None:
    """Parse an OSI model and emit it in the given TARGET format."""
    document = load_osi_document(model_path)
    semantic_model = document.semantic_model[0]
    model = ResolvedModel.build(semantic_model)

    try:
        result = dispatch_transpile(document, model, target, metric, list(group_by) or None)
    except ValueError as exc:
        raise click.UsageError(str(exc))

    for warning in result.warnings:
        click.echo(f"warning: {warning}", err=True)

    if out:
        Path(out).write_text(result.content)
        click.echo(f"Wrote {out}", err=True)
    else:
        click.echo(result.content)


@main.command("export-demo-dataset")
@click.option("--out", type=click.Path(dir_okay=False), required=True, help="Path to write the .duckdb file")
@click.option("--force", is_flag=True, help="Overwrite --out if it already exists")
def export_demo_dataset_cmd(out: str, force: bool) -> None:
    """Write the bundled TPC-DS-shaped demo dataset - the same data the web UI's
    "Demo dataset" run mode uses - to a real .duckdb file, so it can be re-uploaded
    (Run tab's Upload mode) or registered as a duckdb_file connection."""
    try:
        from semantica.demo_data import export_demo_dataset
    except ImportError as exc:
        raise click.UsageError(
            'exporting the demo dataset requires duckdb - install with `pip install "semantica[dev]"` '
            'or `"semantica[api]"`'
        ) from exc

    try:
        export_demo_dataset(out, overwrite=force)
    except FileExistsError as exc:
        raise click.UsageError(f"{exc} (pass --force to overwrite)")

    click.echo(f"Wrote {out}", err=True)
