# Local Event Photo Prep

Free, local-first event photo culling and Lightroom XMP preparation.

Local Event Photo Prep analyzes event photographs on your Mac, groups similar
frames, recommends the strongest moments, and prepares selected RAW files with
individual Adobe Lightroom Classic XMP settings. Photographs stay on your
computer: there is no account, cloud upload, telemetry, subscription, or API
key.

> **Beta software:** Always keep an independent backup and review important
> photographs before delivery. Automated scores assist a photographer; they do
> not replace creative judgment.

## Highlights

- Scans nested event folders containing mixed cameras and formats.
- Supports RAF, NEF, DNG, ARW, CR2/CR3 when the installed RAW decoder can read
  them, plus JPEG and TIFF.
- Measures sharpness, exposure, clipping, faces, visible eyes, smiles, group
  attention, composition, and backlighting locally.
- Groups bursts and near-duplicates while preserving genuinely different
  moments.
- Detects small and mildly blurred faces using a bundled local YuNet model.
- Rejects severely soft detected faces from the automatic KEEP set and applies
  restrained adaptive sharpening to recoverable softness.
- Creates independent Lightroom tone, color, detail, noise, white-balance, and
  lens recommendations for each photograph.
- Keeps permanent human overrides for selections and adjustments.
- Copies only approved KEEP RAW files and matching XMP sidecars to a separate
  Lightroom import folder.

The app performs face detection only. It does not recognize people or create
face identities.

## Safety and privacy

The recommended workflow never deletes, moves, renames, or modifies source
photographs. Analysis writes previews and review data inside `_photo_ai/`.
Export copies approved RAW originals into a separate sibling folder and creates
XMP files beside those copies.

The app rejects overlapping source and destination trees, changed source files,
duplicate KEEP pairs, and conflicting destination files. Existing XMP files are
backed up before the optional advanced source-side workflow replaces them.

No credentials are required. Never commit client photographs, event databases,
Lightroom catalogs, `.env` files, or `.streamlit/secrets.toml` to a fork.

## Installation on macOS

Requirements: macOS and Python 3.10 or newer.

```bash
git clone https://github.com/naveen-bloomintel/local-event-photo-prep.git
cd local-event-photo-prep
chmod +x install_macos.sh run_event_photo_prep.sh
./install_macos.sh
./run_event_photo_prep.sh
```

The installer creates a private `.venv`, installs the project with RAW and
face-detection support, and checks the decoder. For richer metadata and another
embedded-preview fallback, install ExifTool:

```bash
brew install exiftool
```

Verify a real camera file before processing a large event:

```bash
.venv/bin/event-photo-prep doctor /path/to/sample.RAF
```

## Recommended workflow

1. Keep the original camera folders inside one event folder.
2. Launch the app and choose that event folder.
3. Click **Analyze event**. Older compatible `_photo_ai` review databases are
   reused and upgraded automatically.
4. Review KEEP, ALT, REJECT, SOFT FOCUS, and processing-error results.
5. Use **Before / after** to inspect or refine each Lightroom recipe.
6. Open **Finish** and approve the current selection and edits.
7. Choose a separate sibling destination and click **Create Lightroom folder**.
8. In Lightroom Classic, import the prepared folder using **Add** and enable
   **Include subfolders** when appropriate.
9. Spot-check representative group, indoor, outdoor, backlit, and low-light
   photographs before final delivery.

The 1600 px JPEGs shown in the app are review previews. The Lightroom folder
contains untouched full-resolution RAW copies, so the preview size does not
limit final output. Mild softness can sometimes be improved; severe missed
focus or motion blur cannot be reconstructed authentically.

## Output layout

```text
Event_Name/
├── Fuji/*.RAF
├── Nikon/*.NEF
└── _photo_ai/
    ├── previews/
    ├── event-photo-prep.sqlite3
    ├── review.csv
    ├── review.json
    ├── selected.txt
    ├── alternates.txt
    ├── rejects.txt
    └── selection_approved.json

Event_Name_Lightroom_KEEP/
├── Fuji/*.RAF + same-named *.xmp
├── Nikon/*.NEF + same-named *.xmp
└── event-photo-prep-export.json
```

Do not import XMP files separately. Lightroom discovers a sidecar placed beside
the same-named RAW file.

## Command line

```bash
.venv/bin/event-photo-prep analyze /path/to/event
.venv/bin/event-photo-prep doctor /path/to/sample.NEF
.venv/bin/event-photo-prep review /path/to/event
.venv/bin/event-photo-prep summary /path/to/event
.venv/bin/event-photo-prep approve-selection /path/to/event
.venv/bin/event-photo-prep export-selected /path/to/event /path/to/Event_Name_Lightroom_KEEP
```

The advanced `write-xmp` command writes sidecars beside approved source files
and backs up existing sidecars. The recommended `export-selected` command keeps
the source event unchanged.

## Configuration

Edit `config.yaml` to tune preview size, culling thresholds, burst timing,
duplicate sensitivity, people-selection weight, detail thresholds, maximum
exposure recovery, and lens-correction behavior.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[all]'
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/event-photo-prep analyze sample_event
```

The sample event is generated artwork and contains no client photographs.
Architecture and RAW-decoder details are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/RAW_SUPPORT.md](docs/RAW_SUPPORT.md). Before making a fork public, follow
the [publishing checklist](docs/PUBLISHING.md).

## Limitations

- Culling uses explainable local computer-vision measurements, not a cloud
  aesthetic model.
- Small, dark, profile, or obstructed faces may not be detected reliably.
- Global Lightroom controls cannot replace detailed local masking.
- RAW support depends on rawpy/LibRaw, ExifTool, or macOS ImageIO.
- The in-app preview approximates Adobe rendering; Lightroom Classic is the
  authoritative result.

## Contributing and citation

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before sharing examples, especially when they may contain faces or private
event information.

Local Event Photo Prep was created by **Naveen Benjamin**. If this project helps
your work, starring the repository, linking to it, or citing it using
[CITATION.cff](CITATION.cff) helps others discover the project while preserving
creator credit.

## Third-party software

The bundled YuNet face-detection model comes from OpenCV Zoo and retains its
upstream MIT notice. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

Local Event Photo Prep is free and open source under the [MIT License](LICENSE).
