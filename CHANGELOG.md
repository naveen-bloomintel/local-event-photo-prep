# Changelog

## 2.2.0

- Renames the public project to Local Event Photo Prep and adds privacy-safe
  release metadata while retaining compatibility with existing event reviews.
- Uses the bundled YuNet model to detect small and mildly blurred faces that
  the previous Haar-only path missed.
- Classifies print detail as ready, recoverable softness, check detail, or soft
  focus, and prevents severely soft detected faces from entering the automatic
  KEEP set.
- Adds adaptive Lightroom sharpening, edge masking, and a restrained
  scene-aware finishing vignette instead of one near-uniform detail recipe.
- Surfaces detail status in review filters, before/after guidance, Finish
  warnings, and the export manifest.
- Clarifies that in-app JPEGs are review previews while Lightroom receives the
  untouched full-resolution RAW files.

## 2.1.0

- Fixes the OpenCV 5 Laplacian type error that caused every otherwise decoded
  RAF to be marked as a processing error.
- Preserves camera metadata before quality analysis and labels RAW-preview and
  image-analysis failures separately.
- Adds rawpy/LibRaw, ExifTool, and macOS ImageIO dependency diagnostics plus the
  `event-photo-prep doctor` command.
- Fixes mixed numeric types in Streamlit edit sliders and adds headless tests for
  all review workspaces.
- Adds measured per-photo temperature and tint to the independent tone, color,
  detail, noise, and lens recipes.
- Strengthens Lightroom XMP field validation and emits Adobe xpacket wrappers.
- Requires separate review and export confirmations in the app.
- Exports only KEEP RAW files, rejects duplicate KEEP pairs and changed sources,
  verifies existing copies byte-for-byte, and writes a destination manifest.
- Replaces nonfunctional/error-prone review paths with conditional native
  Streamlit workspaces and recoverable error detail.

## 2.0.1

- Safely probes the optional native OpenCV dependency before importing it.
- Falls back to Pillow-based sharpness analysis when OpenCV is unavailable or ABI-incompatible instead of allowing the application process to crash.

## 2.0.0

- Replaces whole-frame-average editing with independent subject-aware tuning for every photo.
- Measures luminance percentiles, center/face/subject brightness, dynamic range, colorfulness, and backlight strength.
- Corrects strongly backlit groups with subject exposure, shadow recovery, and highlight protection.
- Adds ISO-aware noise reduction plus photo-specific sharpening, masking, texture, clarity, and vibrance.
- Preserves As Shot white balance unless the photographer explicitly chooses a custom setting.
- Displays the analysis evidence and tuning explanation for each photograph.
- Preserves manual selections and manual Lightroom settings during reanalysis.
- Adds a one-click Finish action that copies only KEEP RAW files and generates matching XMP files in a separate Lightroom folder.
- Refuses unsafe overlapping export destinations and never overwrites a conflicting RAW copy.
- Adds an MIT license, contribution and security guidance, and GitHub Actions tests for public sharing.
- Expands the suite to 11 tests, including backlight recovery and Lightroom-folder export.

## 1.2.0

- Adds people-aware winner selection for near-duplicate photographs.
- Considers group-relative face completeness, visible/open eyes, smiles, frontal camera attention, and face sharpness.
- Combines people quality with technical quality into a displayed selection score.
- Shows the people-quality evidence in the review grid, burst review, and before/after screen.
- Keeps processing local and performs no face recognition or person identification.
- Reprocesses older event caches once to calculate the new people signals.

## 1.1.0

- Keeps only the technically strongest frame from near-identical photos.
- Marks the others `REJECT — DUPLICATE` and records the selected filename.
- Combines perceptual, difference, and wavelet hashes with color similarity.
- Uses detail, face/subject sharpness, eye quality, clipping, exposure, and composition as technical tie-breakers.
- Keeps separate high-quality moments or compositions even when captured seconds apart.
- Opens the review grid with KEEP-only results.
- Adds duplicate counts and `duplicates.txt`.
- Reprocesses older cached records once to generate the improved similarity signatures.
- Automatically finds Python 3.10+ and gives a direct Python 3.12 installation instruction when macOS Python is too old.
