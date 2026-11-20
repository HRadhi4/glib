<p align="center"><img src="assets/glib-logo.png" alt="Glib" width="260"></p>

# glib

<a href="https://ko-fi.com/hradhi4"><img src="https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white" alt="Support on Ko-fi"></a>

A recording app for narration that is read from a script. It runs entirely on your own
computer: after the one-time set-up, nothing you record leaves it.

Glib shows the script one sentence at a time. For every line you record it can:

- **Polish** your real recording: remove "um" and "uh", repeated words and false starts,
  shorten long pauses, lower background noise and even out the loudness. It compares what you
  said with the script and points out wrong or missing words.
- **Rebuild** the line: a natural British reader says the script exactly as written, and Glib
  gives that reading your voice tone, learned from samples of your voice. No slips, a neutral
  accent and a livelier delivery.

You choose, line by line, which version goes into the final audio file.

## Install (Windows 10 or 11, 64-bit)

1. Download **Glib-Setup.bat** from this page and double-click it. If Windows shows a blue
   "Windows protected your PC" box, choose **More info**, then **Run anyway**.
2. It downloads Glib, installs Python 3.13 if needed, then the parts Glib needs and the voice
   engines. Allow about 4 GB of disk space and a good internet connection.
3. When it finishes, Glib opens and a **Glib** icon is on the desktop.

Already have the folder? Double-click **Install Glib** inside it instead.

## Use

1. **My Voice**: read the text on screen for a few minutes. Five minutes or more gives the best match.
2. **Record**: paste a script, press **Space**, read the line, press **Space** again.
   Green means the take matches the script. Amber means it needs a second look.
3. Use **Rebuild this line** for lines that are hard to get right, or **Rebuild every line**
   for a whole script in the neutral accent.
4. **Export the audio** saves one WAV file, ready for the video editor.

**Settings** has the pause lengths, the reading speed, and a "Say it this way" list for words
that are spoken differently from how they are written (NASA is said "nasa", not spelled out).

## Good to know

- No graphics card is needed. Polish takes a few seconds per line. Rebuild takes roughly two to
  four times the length of the line on an ordinary laptop.
- Polish only keeps a cut after listening again and confirming the line is closer to the script.
  If a slip cannot be removed cleanly, it says so instead of damaging the take.
- The word check is advice, not a verdict: unusual words, names and numbers are sometimes misheard.
- Rebuilt audio is computer-generated speech in your voice tone. Use it only with your own voice.
- "Install extra engines" adds Chatterbox, a second voice converter to try.

## Support

If Glib saves you time, you can buy me a coffee on Ko-fi. It helps me keep adding features and fixing problems.

<a href="https://ko-fi.com/hradhi4"><img src="https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white&style=for-the-badge" alt="Support on Ko-fi"></a>

## Licence

Free for noncommercial use under the PolyForm Noncommercial License 1.0.0 (LICENSE.md).
Commercial use needs a separate licence (COMMERCIAL-LICENSE.md). The voice engines have their
own licences (THIRD-PARTY-NOTICES.md).

## For developers

Python 3.13. `glib/` holds the app: `server.py` (local FastAPI server), `pipeline.py` (Polish,
Rebuild, export), `align.py` (script comparison), `audio.py`, `asr.py`, `tts.py`, `vc.py`,
`models.py` (engine downloads) and `web/index.html` (the interface). Start with `python -m glib`.
