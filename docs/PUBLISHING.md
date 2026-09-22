# Publishing checklist

Use this checklist before making the repository public.

## Identity and attribution

1. Create an empty GitHub repository named `local-event-photo-prep`.
2. Confirm the repository URLs in `README.md` and `CITATION.cff` use the public
   repository owner's GitHub username.
3. Keep `LICENSE` and `CITATION.cff` if you want public creator attribution.
4. Configure Git to use your GitHub-provided no-reply email if you do not want a
   personal email stored in commits.

## Privacy review

1. Confirm that only generated images exist in `sample_event/`.
2. Do not add client photographs, `_photo_ai/`, Lightroom catalogs, exported
   folders, `.env` files, Streamlit secrets, credentials, or private keys.
3. Review every staged filename before the first commit:

   ```bash
   git status --short
   git diff --cached --stat
   ```

4. Search staged text for absolute home paths, emails, tokens, and event names.
5. Enable GitHub secret scanning and push protection. Never bypass a real
   secret warning.

## Repository presentation

Suggested description:

> Free, local-first event photo culling and Lightroom XMP preparation for macOS.

Suggested topics:

`photography`, `photo-culling`, `lightroom`, `xmp`, `raw`, `streamlit`,
`computer-vision`, `privacy`, `macos`, `open-source`

Upload [`assets/social-preview.jpg`](assets/social-preview.jpg) in **Settings →
Social preview**. Use the name, tagline, palette, expanded topic list, and
screenshot privacy rules in [`BRAND.md`](BRAND.md).

After the first successful CI run, create a `v2.2.0` release from the changelog.
Add privacy-safe screenshots or a short demo made only with the generated sample
event. GitHub recognizes `CITATION.cff` and presents citation information on the
repository page.
