# Progress

## 2026-10-07 · Native frontend redesign

Changed soundklaut_gui.py: two-column download/results workspace, stacked layout
below 920 px, graphite palette and pale-blue actions, clearer type hierarchy,
collapsed audio settings, fixed Spotify footer, visible default output folder,
inline validation feedback, busy state, duplicate-submit guard, error-aware
completion, worker exception recovery. Kept existing download backend contracts.
Added DESIGN.md with the explicit replacement of the former section 5 design
rules in ARCHITECTURE.md. Added dev/tests/test_gui_state.py (4 state regressions).

Verified: Python 3.11 compilation; native app launch and screenshot inspection;
Command+Return with empty input visibly logs a warning and focuses source input;
4/4 new state tests pass; git diff --check passes. Existing backend suite: 42 pass,
2 fail (test_download_track_no_playlist_by_default and
 test_download_track_playlist_allowed use outdated call signatures, already
noted in ARCHITECTURE.md). No real external download performed. Narrow layout,
folder picker, and account save not fully interaction-tested. Some subsequent
native screenshots captured macOS window transitions and are not verification.
There is no web deployment or deployed URL for this native desktop application.

Existing uncommitted work at entry: soundklaut.py, soundklaut_gui.py,
dev/requirements.txt, dev/tests/test_soundklaut.py; ARCHITECTURE.md untracked.
Retained that work. No commit/push made because the modified GUI already contains
substantial uncommitted functionality predating this task. The pre-redesign GUI
snapshot is /tmp/soundklaut_gui_before_redesign.py for this machine/session.

Next step: review the open native app at narrow size and with an actual download;
then commit the combined GUI only when the pre-existing changes are accounted
for. Separate backend test-signature cleanup from the design changes.

## 2026-11-10 · Stille in der ganzen Musikbibliothek trimmen
Neu: `dev/trim_library.py` (Stapel für vorhandene Dateien). Erkennung wie `trim_trailing_silence` (pydub, -50 dBFS, 10 ms), zusätzlich am Anfang; Schnitt verlustfrei mit ffmpeg `-c copy` statt Neukodierung; ID3-Tags inklusive Cover danach 1:1 zurückgeschrieben (ohne TLEN), bei M4A Encoder-Tag entfernt. Standard: Anfang ab 0.25 s Stille schneiden und 0.05 s stehen lassen, Ende ab 0.5 s schneiden und 0.25 s stehen lassen. Probelauf ohne `--apply`.

Angewendet auf `~/Documents/Privat/Music/Musik` (114 Dateien): 78 geschnitten (16 auch am Anfang), 36 unverändert, 66.7 min Stille entfernt (520.7 → 453.9 min, 930 MB → 808 MB). Die langen Enden (meist 60 oder 120 s) waren echte Stille (Mittel −71 bis −90 dBFS, Spitzen ≤ −33 dBFS). Backup: `~/Documents/Privat/Music/Musik-Backup-vor-Trim-2026-11-10`.

Verifiziert: alle 114 Dateien dekodieren fehlerfrei (ffmpeg); neue Länge = geplanter Schnitt (±0.15 s); Nachmessung ohne Stille über den Schwellen; Tags und Cover aller Dateien gleich wie im Backup (ausser TLEN und dem bei Schnitt ungültigen iTunSMPB); unveränderte Dateien bytegleich. Nicht angehört.

Nächster Schritt: Backup löschen, sobald Roman die Songs geprüft hat; optional Trim am Anfang auch beim Download in soundklaut.py (bestehende uncommitted Änderungen dort vorher klären).
