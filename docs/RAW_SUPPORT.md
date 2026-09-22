# RAW support and diagnostics

Local Event Photo Prep uses a fallback chain so one missing tool does not stop
an event:

1. rawpy extracts the camera's embedded JPEG;
2. rawpy/LibRaw renders the sensor data when the embedded image is absent;
3. ExifTool tries `PreviewImage`, `JpgFromRaw`, `OtherImage`, and
   `ThumbnailImage`;
4. macOS ImageIO (`sips`) is the final local fallback.

A decoded preview must have a shortest edge of at least 480 pixels. Smaller
thumbnails are unsuitable for face, focus, and duplicate judgments, so the app
continues to the next decoder instead of silently accepting them.

## Check a camera file

```bash
./install_macos.sh
.venv/bin/event-photo-prep doctor /path/to/sample.RAF
```

Successful output includes `sample_decoded: true`, preview dimensions, and the
rawpy/LibRaw versions. ExifTool is recommended for complete camera, lens, and
capture metadata:

```bash
brew install exiftool
```

## Read an error record

Each `_photo_ai/review.json` record distinguishes:

- `RAW preview failed`: no decoder produced a useful image;
- `Image analysis failed`: preview decoding succeeded, but quality or scene
  analysis failed.

Failed photographs are labeled `PROCESSING ERROR`, retried on the next analysis,
and excluded from XMP writing and export. Camera groups still derive from `.RAF`
and `.NEF` extensions when richer metadata cannot be read.

When reporting compatibility, include the sanitized `event-photo-prep doctor`
output, macOS version, camera make/model, compression mode, and whether the same
file opens in the current Lightroom Classic. Never attach a client's RAW file
without permission.
