"""Lexis CLI: `lexis transpile <model.yaml> --target <target> ...`"""

import os
import re
from contextlib import contextmanager
from pathlib import Path

import click

from lexis.dispatch import TARGETS
from lexis.dispatch import transpile as dispatch_transpile
from lexis.parser import load_ossie_document
from lexis.resolved_model import ResolvedModel

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@click.group()
def main() -> None:
    """Lexis: transpile Ossie semantic models to warehouse SQL and BI/AI formats."""


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
    """Parse an Ossie model and emit it in the given TARGET format."""
    document = load_ossie_document(model_path)
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
        from lexis.demo_data import export_demo_dataset
    except ImportError as exc:
        raise click.UsageError(
            'exporting the demo dataset requires duckdb - install with `pip install "lexis-cli[mcp]"`'
        ) from exc

    try:
        export_demo_dataset(out, overwrite=force)
    except FileExistsError as exc:
        raise click.UsageError(f"{exc} (pass --force to overwrite)")

    click.echo(f"Wrote {out}", err=True)


@contextmanager
def _demo_connection(model: ResolvedModel):  # noqa: ARG001 - model kept for signature symmetry with the other two connection helpers
    try:
        from lexis.demo_data import build_tpcds_demo_connection
    except ImportError as exc:
        raise click.UsageError(
            '--demo requires duckdb - install with `pip install "lexis-cli[mcp]"`'
        ) from exc

    # Unlike the API's `/run` endpoint (which checks demo-compatibility per request,
    # for just the one metric being queried - see `duckdb_run.check_demo_compatible`),
    # we don't know which metric will be called until a tool call arrives, so we can't
    # reject up front without also rejecting metrics that don't touch an unsupported
    # table. Let an incompatible metric fail naturally with DuckDB's own "table/catalog
    # not found" error when it's actually invoked.
    con = build_tpcds_demo_connection()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def _duckdb_file_connection(model: ResolvedModel, path: str):
    try:
        import duckdb
    except ImportError as exc:
        raise click.UsageError(
            '--duckdb-file requires duckdb - install with `pip install "lexis-cli[mcp]"`'
        ) from exc

    catalogs = {ds.source.split(".", 1)[0] for ds in model.datasets.values()}
    if len(catalogs) != 1:
        raise click.UsageError(
            "--duckdb-file requires every dataset in the model to share one catalog name "
            f"in its `source`; found {sorted(catalogs)}"
        )
    catalog = catalogs.pop()
    if not _SAFE_IDENTIFIER_RE.match(catalog):
        raise click.UsageError(f"invalid catalog name in source: {catalog!r}")

    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{path}' AS {catalog} (READ_ONLY)")
        yield con
    finally:
        con.close()


@contextmanager
def _snowflake_connection(
    account: str,
    user: str,
    password_env: str,
    warehouse: str | None,
    database: str | None,
    schema: str | None,
    role: str | None,
):
    try:
        import snowflake.connector
    except ImportError as exc:
        raise click.UsageError(
            '--snowflake-account requires snowflake-connector-python - install with '
            '`pip install "lexis-cli[mcp]"`'
        ) from exc

    password = os.environ.get(password_env)
    if not password:
        raise click.UsageError(f"environment variable {password_env!r} (--snowflake-password-env) is not set")

    con = snowflake.connector.connect(
        account=account,
        user=user,
        password=password,
        warehouse=warehouse,
        database=database,
        schema=schema,
        role=role,
    )
    try:
        yield con
    finally:
        con.close()


@main.command("mcp-serve")
@click.argument("model_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--demo", is_flag=True, help="Run against the bundled TPC-DS demo dataset")
@click.option("--duckdb-file", type=click.Path(exists=True, dir_okay=False), help="Run against a local .duckdb file")
@click.option("--snowflake-account", help="Run against Snowflake (requires --snowflake-user/-password-env)")
@click.option("--snowflake-user")
@click.option("--snowflake-password-env", help="Env var holding the Snowflake password")
@click.option("--snowflake-warehouse")
@click.option("--snowflake-database")
@click.option("--snowflake-schema")
@click.option("--snowflake-role")
def mcp_serve(
    model_path: str,
    demo: bool,
    duckdb_file: str | None,
    snowflake_account: str | None,
    snowflake_user: str | None,
    snowflake_password_env: str | None,
    snowflake_warehouse: str | None,
    snowflake_database: str | None,
    snowflake_schema: str | None,
    snowflake_role: str | None,
) -> None:
    """Serve MODEL's metrics as live MCP tools over stdio (e.g. for Claude Desktop) -
    one `query_<metric>` tool per metric, executed against the demo dataset, a local
    DuckDB file, or Snowflake."""
    try:
        import anyio
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise click.UsageError(
            'mcp-serve requires the `mcp` package - install with `pip install "lexis-cli[mcp]"`'
        ) from exc

    if sum(bool(x) for x in (demo, duckdb_file, snowflake_account)) != 1:
        raise click.UsageError("pass exactly one of --demo, --duckdb-file, or --snowflake-account")

    document = load_ossie_document(model_path)
    model = ResolvedModel.build(document.semantic_model[0])

    from lexis import mcp_server as mcp_server_module
    from lexis.transpilers.sql import DuckDBEmitter, SnowflakeEmitter

    if demo:
        con_cm, emitter = _demo_connection(model), DuckDBEmitter()
    elif duckdb_file:
        con_cm, emitter = _duckdb_file_connection(model, duckdb_file), DuckDBEmitter()
    else:
        if not (snowflake_user and snowflake_password_env):
            raise click.UsageError("--snowflake-account requires --snowflake-user and --snowflake-password-env")
        con_cm = _snowflake_connection(
            snowflake_account,
            snowflake_user,
            snowflake_password_env,
            snowflake_warehouse,
            snowflake_database,
            snowflake_schema,
            snowflake_role,
        )
        emitter = SnowflakeEmitter()

    with con_cm as con:

        def execute(metric: str, group_by: list[str] | None) -> dict:
            return mcp_server_module.run_metric_query(con, emitter, model, metric, group_by)

        server = mcp_server_module.build_server(model, execute)

        async def _run() -> None:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        anyio.run(_run)
