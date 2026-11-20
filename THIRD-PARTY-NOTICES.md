# Third-party components

Glib's own code is covered by LICENSE.md. It relies on the components below, which keep
their own licences. Glib does not include them in its source; the installer fetches them.

## Voice engines (downloaded on first run into data/models)

| Engine | Used for | Licence |
|---|---|---|
| NVIDIA Parakeet TDT 0.6B v2 (ONNX build from the sherpa-onnx project) | Listening to recordings | CC-BY-4.0 (credit NVIDIA) |
| Kokoro v1.0 (hexgrad), ONNX build from kokoro-onnx | British reader | Apache-2.0 |
| WavLM-Large (Microsoft) | Voice conversion | MIT |
| kNN-VC HiFi-GAN vocoder (Baas, van Niekerk, Kamper) | Voice conversion | MIT |

## Code included in this folder

- `glib/vendor/knnvc`: kNN-VC (https://github.com/bshall/knn-vc), MIT, with WavLM model code
  (Microsoft, MIT) and HiFi-GAN model code (Jungil Kong et al., MIT). Licence text is in that folder.

## Python packages (installed by the installer)

sherpa-onnx (Apache-2.0), kokoro-onnx (MIT), onnxruntime (MIT), PyTorch and torchaudio (BSD-3-Clause),
NumPy and SciPy (BSD-3-Clause), soundfile (BSD-3-Clause; libsndfile LGPL-2.1), sounddevice (MIT;
PortAudio MIT), FastAPI (MIT), Uvicorn (BSD-3-Clause), python-multipart (Apache-2.0).

**Note on GPL components.** kokoro-onnx works out pronunciation with `phonemizer` (GPL-3.0-or-later)
and the eSpeak NG library (GPL-3.0-or-later, loaded through `espeakng-loader`). They are separate
programs' libraries that the installer downloads; Glib does not copy their code. Anyone who
redistributes Glib together with them, or sells commercial licences for Glib, should take legal
advice on how the GPL applies, or replace that pronunciation step first.

## Optional extra engines (only if "Install extra engines" is run)

- Chatterbox (Resemble AI), MIT. Its output carries Resemble's inaudible Perth watermark.
- faster-whisper (MIT) with OpenAI Whisper models (MIT).

## Logo

The Glib logo files in `assets` and `glib/web/assets` belong to the copyright holder of Glib.
