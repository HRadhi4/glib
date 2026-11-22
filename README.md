# Glib voice engine files

Files Glib downloads on first use for its "Closest to my voice" engine. They are ONNX
conversions of kNN-VC (Baas, van Niekerk and Kamper, 2023), so they run without PyTorch.

| File | What it is | Licence |
|---|---|---|
| `wavlm_l6.onnx` (in parts, joined on download) | WavLM-Large (Microsoft), first 6 transformer layers | MIT |
| `hifigan_prematched.onnx` | kNN-VC prematched HiFi-GAN vocoder, 16 kHz | MIT |

`SHA256SUMS` lists the checksums of the joined files.
