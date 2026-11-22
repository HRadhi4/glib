# Third-party components

Glib's own code is covered by LICENSE.md. It relies on the components below, which keep
their own licences.

## Voice engines (downloaded on first run into the Glib data folder)

| Engine | Used for | Licence |
|---|---|---|
| NVIDIA Parakeet TDT 0.6B v2 (ONNX build from the sherpa-onnx project) | Listening to recordings | CC-BY-4.0 (credit NVIDIA) |
| DPDFNet-2 48 kHz HR (Ceva), ONNX build from the sherpa-onnx project | Noise removal | Apache-2.0 |
| Kokoro v1.0 (hexgrad), ONNX build from kokoro-onnx | British reader | Apache-2.0 |
| Chatterbox voice conversion (Resemble AI) | Speaking in your voice | MIT |
| Chatterbox ONNX export (onnx-community; INT8 build by TigreGotico) | Running Chatterbox without PyTorch | Apache-2.0 |

Chatterbox's optional Perth watermark is not applied by Glib.

## Bundled with the installer

- Python 3.12 runtime (python-build-standalone): Python Software Foundation License.
- sherpa-onnx (Apache-2.0), kokoro-onnx (MIT), ONNX Runtime (MIT), NumPy and SciPy (BSD-3-Clause),
  soundfile (BSD-3-Clause; libsndfile LGPL-2.1), sounddevice (MIT; PortAudio MIT), FastAPI (MIT),
  Starlette (BSD-3-Clause), Uvicorn (BSD-3-Clause), Pydantic (MIT), python-multipart (Apache-2.0),
  and their dependencies, each under its own licence.

**Note on GPL components.** kokoro-onnx works out pronunciation with `phonemizer` (GPL-3.0-or-later)
and the eSpeak NG library (GPL-3.0-or-later, loaded through `espeakng-loader`). Glib does not copy
or change their code. Anyone who sells commercial licences for Glib should take legal advice on how
the GPL applies to distributing them together, or replace that pronunciation step first.

## Installer

Built with Inno Setup (Jordan Russell and Martijn Laan, Inno Setup License).

## Logo

The Glib logo files in `assets`, `installer` and `glib/web/assets` belong to the copyright holder of Glib.
