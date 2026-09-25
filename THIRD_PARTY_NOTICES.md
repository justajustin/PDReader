# Third-party notices

PDReader's MIT license covers the original client code and authored demo assets. Third-party libraries retain their own licenses.

- **KaTeX 0.16.21** — https://github.com/KaTeX/KaTeX (MIT). Bundled JavaScript, CSS and fonts live in `web/vendor/katex/`; see `web/vendor/katex/LICENSE`. Fonts are restored from the matching upstream npm package.
- **QRCode.js** — https://github.com/davidshimjs/qrcodejs (MIT). See `web/vendor/qrcode.LICENSE`. The pre-existing minified file does not contain a version identifier, so no exact release is claimed.

Python dependencies are declared in `pyproject.toml` and installed separately. When distributing binaries, retain the notices supplied by those dependencies and PyInstaller hooks, including the PDFium notices shipped by pypdfium2. Review the contents of the actual build before distributing an installer.
