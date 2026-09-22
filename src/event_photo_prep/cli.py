from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .pipeline import analyze_event, build_summary
from .preview import dependency_report, open_photo
from .workflow import approve_selection, export_selected, load_records, write_approved_xmp

app = typer.Typer(help="Local Event Photo Prep — nondestructive event photo preparation")
console = Console()


@app.command()
def doctor(
    sample: Annotated[Path | None, typer.Argument(help="Optional RAF or NEF file to decode.")] = None,
) -> None:
    """Check RAW dependencies and optionally decode one RAF or NEF file."""
    report = dependency_report()
    if sample is not None:
        try:
            image = open_photo(sample.expanduser().resolve())
            report["sample"] = str(sample)
            report["sample_decoded"] = True
            report["sample_size"] = f"{image.width}x{image.height}"
        except Exception as error:
            report["sample"] = str(sample)
            report["sample_decoded"] = False
            report["sample_error"] = f"{type(error).__name__}: {error}"
    console.print_json(data=report)
    if not report["raw_preview_available"] or report.get("sample_decoded") is False:
        raise typer.Exit(1)


@app.command()
def analyze(event: Path, config: Path | None = None) -> None:
    """Analyze or resume an event folder."""
    def progress(done: int, total: int, name: str) -> None:
        console.print(f"[{done}/{total}] {name}")
    summary_data = analyze_event(event, config, progress)
    console.print_json(data=summary_data)


@app.command()
def review(event: Path) -> None:
    """Open the local Streamlit review application."""
    root_app = Path(__file__).with_name("app.py")
    command = [sys.executable, "-m", "streamlit", "run", str(root_app), "--", "--event", str(event)]
    raise typer.Exit(subprocess.call(command))


@app.command()
def summary(event: Path, config: Path | None = None) -> None:
    """Show current event summary."""
    console.print_json(data=build_summary(load_records(event, config)))


@app.command("approve-selection")
def approve(event: Path, config: Path | None = None) -> None:
    """Approve the current KEEP/ALT/REJECT decisions."""
    console.print(f"Approved: {approve_selection(event, config)}")


@app.command("write-xmp")
def write_sidecars(event: Path, config: Path | None = None) -> None:
    """Write XMP only for an unchanged, explicitly approved selection."""
    console.print_json(data=write_approved_xmp(event, config))


@app.command("export-selected")
def copy_selected(event: Path, destination: Path, config: Path | None = None) -> None:
    """Prepare a Lightroom folder with selected RAW files and generated XMP."""
    def progress(done: int, total: int, name: str) -> None:
        console.print(f"[{done}/{total}] {name}")

    console.print_json(data=export_selected(event, destination, config, progress))


if __name__ == "__main__":
    app()
