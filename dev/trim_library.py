"""Stille am Anfang und Ende vorhandener Songs entfernen (Ordner im Stapel).

Erkennung wie soundklaut.trim_trailing_silence: pydub detect_leading_silence, Schwelle -50 dBFS,
10-ms-Schritte, zusaetzlich fuer den Anfang. Geschnitten wird verlustfrei mit ffmpeg (-c copy):
keine Neukodierung; ID3-Tags (inkl. Cover) werden danach 1:1 zurueckgeschrieben, ohne TLEN.

Nutzung:
  python3.11 dev/trim_library.py ORDNER            # Probelauf: nur messen, nichts aendern
  python3.11 dev/trim_library.py ORDNER --apply    # schneiden (vorher Backup anlegen!)
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

EXT = {'.mp3', '.m4a'}


def measure(path: Path, thresh: float):
    audio = AudioSegment.from_file(path)
    lead = detect_leading_silence(audio, silence_threshold=thresh, chunk_size=10)
    tail = detect_leading_silence(audio.reverse(), silence_threshold=thresh, chunk_size=10)
    return len(audio), lead, tail


def cut(path: Path, start_s: float, end_s: float):
    # ID3 vorher sichern: ffmpeg schreibt Kommentare (COMM) als TXXX und setzt ein Encoder-Tag (wie soundklaut)
    saved = None
    if path.suffix == '.mp3':
        try:
            saved = ID3(path)
        except Exception:
            saved = None
    tmp = path.with_name(path.stem + '.trim-tmp' + path.suffix)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', f'{start_s:.3f}', '-to', f'{end_s:.3f}', '-i', str(path),
           '-map', '0', '-c', 'copy', '-map_metadata', '0']
    if path.suffix == '.mp3':
        cmd += ['-id3v2_version', '3', '-write_xing', '1']
    else:
        cmd += ['-movflags', '+faststart', '-disposition:v', 'attached_pic']
    cmd.append(str(tmp))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 10_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr.strip()[:300] or 'ffmpeg ohne Ausgabe')
    tmp.replace(path)
    if saved is not None:
        saved.delall('TLEN')  # alte Laenge waere falsch
        saved.save(path, v2_version=saved.version[1] if saved.version[1] in (3, 4) else 4)
    elif path.suffix == '.m4a':
        f = MP4(path)  # iTunSMPB (Gapless) faellt beim Schnitt weg und waere ohnehin falsch; Encoder-Tag entfernen
        if f.tags and '©too' in f.tags:
            del f.tags['©too']
            f.save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--threshold', type=float, default=-50.0, help='dBFS wie soundklaut (Standard -50)')
    ap.add_argument('--min-lead', type=float, default=0.25, help='Anfang erst ab so viel Stille schneiden (s)')
    ap.add_argument('--min-tail', type=float, default=0.5, help='Ende erst ab so viel Stille schneiden (s)')
    ap.add_argument('--pad-lead', type=float, default=0.05, help='so viel Stille vor dem ersten Ton stehen lassen (s)')
    ap.add_argument('--pad-tail', type=float, default=0.25, help='so viel Stille nach dem letzten Ton stehen lassen (s)')
    a = ap.parse_args()
    files = sorted(p for p in Path(a.folder).expanduser().iterdir() if p.suffix.lower() in EXT and not p.name.startswith('.'))
    report = []
    for p in files:
        try:
            total, lead, tail = measure(p, a.threshold)
        except Exception as e:
            report.append({'file': p.name, 'error': f'nicht lesbar: {e}'[:200]}); print(f'FEHLER {p.name}: {e}', file=sys.stderr); continue
        total_s, lead_s, tail_s = total / 1000, lead / 1000, tail / 1000
        if lead >= total:  # ganz still oder unter der Schwelle
            report.append({'file': p.name, 'skip': 'komplett unter der Schwelle'}); continue
        start = max(0.0, lead_s - a.pad_lead) if lead_s >= a.min_lead else 0.0
        end = min(total_s, total_s - tail_s + a.pad_tail) if tail_s >= a.min_tail else total_s
        removed = start + (total_s - end)
        row = {'file': p.name, 'duration': round(total_s, 2), 'lead': round(lead_s, 2), 'tail': round(tail_s, 2),
               'start': round(start, 3), 'end': round(end, 3), 'removed': round(removed, 2)}
        if removed < 0.05:
            row['skip'] = 'keine nennenswerte Stille'
        elif a.apply:
            try:
                cut(p, start, end)
                row['done'] = True
            except Exception as e:
                row['error'] = str(e)
        report.append(row)
        print(f"{'OK ' if row.get('done') else '   '}{p.name[:60]:60} Anfang {lead_s:5.2f}s Ende {tail_s:5.2f}s  -> weg {removed:5.2f}s{'  ' + row.get('skip', '') if row.get('skip') else ''}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
