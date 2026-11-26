# Solo violin recordings

Fifteen sustained, vibrato "Arco Vib" notes (forte, G3 to C7) from **VS Chamber
Orchestra: Community Edition** by Sam Gossner and Simon Dalzell, released under
**CC0 1.0 (public domain)**: https://github.com/sgossner/VSCO-2-CE

The originals were converted to mono, 22.05 kHz, 16-bit and trimmed to 4 seconds.
File names are note names (`G3.wav`, `A5.wav`); `voyager/score_audio.py` shifts the nearest
recording to each requested pitch and loops the sustain for long notes.

The `spiccato/` folder contains two short-bow takes (`rr1`, `rr2`) at each of
G3, A3, C4, E4, G4, A4, C5, E5, G5, A5 and C6. They are the `v1` recordings
from the [VSCO 2 CE solo-violin spic directory](https://github.com/sgossner/VSCO-2-CE/tree/440300901dfe9275fd84e0b7763af1f8443ae62e/Strings/Solo%20Violin/spic)
at revision `440300901dfe9275fd84e0b7763af1f8443ae62e`, also CC0 1.0.
Each original `LLVln_spic_<note>_v1_rr<take>.wav` was converted with ffmpeg
(`-ac 1 -ar 22050 -c:a pcm_s16le`) and renamed `<note>_rr<take>.wav`; no
trimming was applied. Playback pitch-shifts the nearest recording and alternates
the two takes for repeated pitches without looping. Only explicitly marked
MusicXML staccato, staccatissimo and spiccato notes use these recordings.
When MIDI drives playback, its notes do not carry these MusicXML marks.
