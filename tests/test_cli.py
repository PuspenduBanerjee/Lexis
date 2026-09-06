"""CLI tests for `lexis export-demo-dataset` (the `transpile` command is
exercised end-to-end via the README's own examples, not unit-tested here)."""

import duckdb
import pytest
from click.testing import CliRunner

from lexis.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_export_demo_dataset_writes_a_working_duckdb_file(runner, tmp_path):
    out_path = tmp_path / "demo.duckdb"
    result = runner.invoke(main, ["export-demo-dataset", "--out", str(out_path)])

    assert result.exit_code == 0, result.output
    assert out_path.exists()

    # Connecting to the file directly (rather than the app's `ATTACH ... AS tpcds`
    # pattern) exposes its data under its own default catalog, so no `tpcds.` prefix.
    con = duckdb.connect(str(out_path), read_only=True)
    rows = con.execute("SELECT SUM(ss_ext_sales_price) FROM public.store_sales").fetchall()
    con.close()
    assert rows == [(260.0,)]


def test_export_demo_dataset_refuses_to_overwrite_without_force(runner, tmp_path):
    out_path = tmp_path / "demo.duckdb"
    out_path.write_bytes(b"not a real duckdb file")

    result = runner.invoke(main, ["export-demo-dataset", "--out", str(out_path)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_export_demo_dataset_force_overwrites(runner, tmp_path):
    out_path = tmp_path / "demo.duckdb"
    out_path.write_bytes(b"not a real duckdb file")

    result = runner.invoke(main, ["export-demo-dataset", "--out", str(out_path), "--force"])
    assert result.exit_code == 0, result.output

    con = duckdb.connect(str(out_path), read_only=True)
    con.close()
