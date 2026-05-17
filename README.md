# SubLens

> Real-time OCR-powered game dialog translator for Windows — reads text from any screen region and displays the translation in a draggable overlay above your game.

<p align="center">
  <img src="SubLens.ico" alt="SubLens" width="80"/>
</p>

---

## Features

- **3 translation engines** — switch at any time
  - **LM Studio** — fully local AI, no internet required (resource-intensive)
  - **DeepL Free** — 500,000 characters/month, high quality
  - **Google Translate** — unofficial free endpoint, no API key needed
- **Smart OCR** powered by Tesseract
  - 6 preprocessing modes (auto, light text, dark text, subtitle top-hat, stroke/outline, equalize)
  - Otsu thresholding + median filter + contrast enhancement
  - 2× / 3× / 4× upscaling options
  - PSM mode selection (single block, single line, sparse text, raw line)
  - Automatic best-mode detection (tries all 6 modes, picks highest-confidence result)
- **Transparent overlay** — floats above the game, color-coded per engine, draggable
- **Continuous scan** — configurable interval (0.5–15 s), auto-translates when new text is detected
- **Similarity threshold** — skips re-translation on minor OCR jitter
- **LRU translation cache** — 200 entries, avoids redundant API calls
- **Global hotkeys** — work even in fullscreen games (F2 / F3 / F4 + Ctrl+Alt+R/T/G/H)
- **Auto-pause** — scanning pauses when the target game window loses focus
- **Glossary** — protect proper nouns and custom terms from being translated
- **System tray** — minimize to tray, restore with a double-click
- **Multi-monitor** support
- **Config** auto-saved to `%APPDATA%\SubLens\config.json`

---

## Requirements

| Dependency | Notes |
|---|---|
| Python 3.9+ | |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | Install to `C:\Program Files\Tesseract-OCR\` |
| Pillow | `pip install pillow` |
| pytesseract | `pip install pytesseract` |
| PySide6 | `pip install PySide6` |
| mss *(optional)* | Faster multi-monitor capture — `pip install mss` |
| keyboard *(optional)* | Global hotkeys — `pip install keyboard` |
| pywin32 *(optional)* | Auto-pause feature — `pip install pywin32` |

Install all at once:

```bash
pip install pillow pytesseract PySide6 mss keyboard pywin32
```

> **Tesseract language packs** — during Tesseract installation, select the languages you need (`eng`, `tur`, `jpn`, `kor`, etc.). If a pack is missing, the app falls back to `eng` and logs a warning.

---

## Installation

```bash
git clone https://github.com/your-username/SubLens.git
cd SubLens
pip install pillow pytesseract PySide6 mss keyboard pywin32
python sublens.py
```

---

## Quick Start

1. Run `python sublens.py`
2. Select a **translation engine** (Google requires no setup — great for a first try)
3. Choose **source** and **target** languages
4. Press **F2** to draw a rectangle around the dialog box in your game
5. Press **F3** for a one-shot translation, or **F4** to start continuous scanning

---

## Hotkeys

| Key | Action |
|---|---|
| **F2** | Select screen region |
| **F3** | Translate once |
| **F4** | Start / stop continuous scan |
| **ESC** | Hide overlay / cancel region selection |
| **Ctrl+Alt+R** | Select region (global) |
| **Ctrl+Alt+T** | Translate once (global) |
| **Ctrl+Alt+G** | Toggle scan (global) |
| **Ctrl+Alt+H** | Hide overlay (global) |

---

## Engine Setup

### LM Studio
1. Open LM Studio → load a model → start **Local Server** (default port: 1234)
2. In SubLens Settings, enter the **URL** and **Model**, then click **Connect** to verify
- ✅ Fully offline, privacy-friendly
- ⚠️ GPU/RAM intensive — may reduce FPS in demanding games

### DeepL Free
1. Create a free account at [deepl.com](https://www.deepl.com/) → get a Free API key
2. Paste the key into SubLens Settings → click **Test** to check monthly usage
- ✅ Highest translation quality, low resource usage
- ⚠️ 500k character/month limit

### Google Translate
- No API key required, works instantly
- ✅ Zero setup
- ⚠️ Unofficial endpoint — Google may rate-limit or block it occasionally

---

## OCR Tips

- **Scale**: try 3× or 4× for small text
- **OCR Mode**:
  - *Auto* — selects mode based on background brightness
  - *Light text* — bright text on dark background
  - *Dark text* — dark text on light background
  - *Subtitle (top-hat)* — **best for complex/busy backgrounds** (water, blurred landscapes, UI elements). Uses local background removal + adaptive thresholding. Great for games like RDR2 or Spider-Man 2.
  - *Stroke outline* — for outlined/contoured subtitle text
  - *Equalize* — histogram equalization for highly varied backgrounds
- **PSM 6** works well for most dialog boxes; try **PSM 7** for single-line subtitles
- Enable **Preview processed image** to see exactly what Tesseract receives — invaluable for tuning

---

## Game Context (LM Studio only)

In Settings → **Game Context**, you can provide a hint to guide the translation tone:

> Example: `Wild West, 1899, cowboy dialogue`

DeepL and Google ignore this field.

---

## Glossary

In Settings → **Glossary**, add one entry per line:

```
Arthur=Arthur
RedDead
Guarma=Guarma
```

- `term` alone — keeps the word as-is (no translation)
- `source=target` — replaces the source term with `target` after translation

---

## Troubleshooting

| Symptom | Solution |
|---|---|
| "Tesseract language pack not found" | Add the `.traineddata` file for the required language to the Tesseract folder |
| OCR returns empty text | Tighten the region, increase scale, or manually select OCR mode |
| Google engine errors | Temporarily switch to DeepL or LM Studio — Google may be rate-limiting your IP |
| Overlay appears in the wrong position | Click and drag it; position persists until the next launch |
| LM Studio not connecting | Ensure Local Server is running in LM Studio and the URL is correct |
| Low FPS while translating | Increase the scan interval, or switch to DeepL/Google |

---

## Configuration File

`%APPDATA%\SubLens\config.json` — loaded on startup, saved on exit. Safe to edit manually; delete it to reset all settings.

---

## Building a Standalone EXE

```bash
python _build.py
```

The resulting `SubLens.exe` is placed in the `dist/` folder. Tesseract is bundled inside the executable — no separate installation needed on the target machine.

---

## Project Structure

```
SubLens/
├── sublens.py        # Main application (PySide6)
├── _build.py         # PyInstaller build script
├── SubLens.spec      # PyInstaller spec file
├── SubLens.ico       # Application icon
├── READMEapp.md      # In-app help document
├── sublens.bat       # Run helper (bat)
└── calistir.bat      # Alternative launcher
```

---

## License

This project is released under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## Acknowledgements

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — UB Mannheim Windows builds
- [PySide6](https://doc.qt.io/qtforpython/) — Qt for Python
- [mss](https://python-mss.readthedocs.io/) — fast screen capture
- [DeepL API](https://www.deepl.com/docs-api) — high-quality neural translation
