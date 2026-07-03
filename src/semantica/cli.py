"""Semantica CLI: `semantica transpile <model.yaml> --target <target> ...`"""

from pathlib import Path

import click

from semantica.parser import load_osi_document
from semantica.resolved_model import ResolvedModel
from semantica.transpilers.cube import emit_cube_yaml
from semantica.transpilers.dbt_osi import emit_dbt_osi_document
from semantica.transpilers.mcp import emit_mcp_tool_manifest
from semantica.transpilers.sql import EMITTERS as SQL_EMITTERS

TARGETS = [*SQL_EMITTERS.keys(), "cube", "dbt", "mcp"]


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

    if target in SQL_EMITTERS:
        if not metric:
            raise click.UsageError(f"--metric is required for target {target!r}")
        emitter = SQL_EMITTERS[target]()
        content = emitter.emit_metric_query(model, metric, group_by=list(group_by) or None)
    elif target == "cube":
        content = emit_cube_yaml(model)
    elif target == "dbt":
        result = emit_dbt_osi_document(document)
        for warning in result.warnings:
            click.echo(f"warning: {warning}", err=True)
        content = result.artifact.content
    elif target == "mcp":
        content = emit_mcp_tool_manifest(model)
    else:  # pragma: no cover - guarded by click.Choice
        raise click.UsageError(f"Unknown target {target!r}")

    if out:
        Path(out).write_text(content)
        click.echo(f"Wrote {out}", err=True)
    else:
        click.echo(content)
