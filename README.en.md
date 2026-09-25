# PDReader

**Read the slide. Understand the idea. Ask the next question.**

A Windows desktop study companion that brings PPT / PDF pages, AI-generated explanations, and contextual questions into one workspace.

[中文](README.md) · [Usage guide (Chinese)](docs/USAGE.md) · [Contributing](CONTRIBUTING.md)

![PDReader workspace](docs/assets/workspace-light.png)

*Rendered with the real frontend and authored demo content. The example answer is illustrative, not a recorded model result.*

## What you can do

- Read `.ppt`, `.pptx`, and `.pdf` files alongside slide thumbnails.
- Generate explanations for one page or an entire deck, with local caching.
- Ask follow-up questions with the current page, relevant text, and attached screenshots.
- Read typeset math; request supported diagrams, surfaces, or educational animations.
- Save important slides and Q&A, and switch between light, dark, system, and eye-care themes.
- Connect your own compatible AI endpoint and model.

## Run from source

Requires 64-bit Windows 10 / 11, Python 3.11+, and WebView2. PowerPoint or COM-compatible WPS Presentation is needed for PPT files; PDF works without Office.

```powershell
git clone https://github.com/justajustin/PDReader.git
cd PDReader
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PPT_STUDY_DISABLE_PLATFORM = "1"
.\.venv\Scripts\python.exe -m ppt_study
```

Open Settings, enter your Base URL, API key and model, then select the personal API route. Vision features require an image-capable model. Run from the checkout: the frontend is stored in `web/`.

The environment variable above disables platform connections, including registration, telemetry, credits and update checks. Without it, the client contacts its configured platform even when using your own AI API. Model requests send page content and conversation context to the selected provider. **API keys are currently stored in plaintext** under `%APPDATA%\PPTStudyCompanion\settings.json`. See [data and networking details](docs/PRIVACY.md).

## Develop and build

```powershell
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1
powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1
```

The initial public version, 0.2.14, provides source and build scripts; no prebuilt installer is attached. Windows is the supported desktop target. PDF media support varies with the file and codec. AI answers should be checked against the original material.

## Scope and license

MIT-licensed desktop client, including rendering, AI integration, tests and packaging. The hosted credit service, operator backend and payment processing are separate and are not included. Your own API does not require them. The public package contains a recharge placeholder rather than a personal payment QR code.

See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). Issues and pull requests are welcome.
