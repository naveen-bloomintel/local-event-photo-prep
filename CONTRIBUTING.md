# Contributing to Local Event Photo Prep

Thank you for helping improve Local Event Photo Prep. The project prioritizes
safe, nondestructive handling of photographers' originals.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[all]'
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

## Pull requests

1. Create a focused branch and keep changes narrowly scoped.
2. Add tests for new culling, tuning, XMP, or file-handling behavior.
3. Run the complete test suite before opening a pull request.
4. Explain any change that can affect selection decisions or Lightroom output.
5. Never add code that deletes, moves, renames, or modifies source photographs.

Test new XMP fields with current Lightroom Classic on copies before proposing
them. Do not commit event photographs, catalogs, generated `_photo_ai` folders,
credentials, or personally identifying face data.

For RAF/NEF changes, run `event-photo-prep doctor` against a private local
sample and report only the camera model, decoder versions, dimensions, and
sanitized error. Do not add client RAW files as fixtures; use generated images
and decoder mocks.

## Reporting tuning examples

Useful reports include the camera model, lens, ISO, lighting condition, the
generated XMP values, and a privacy-safe reduced preview when sharing is
permitted. Avoid publishing client or event photographs without consent.
