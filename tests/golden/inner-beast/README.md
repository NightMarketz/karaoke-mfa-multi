# Inner Beast golden sample

User-provided reference for MVP alignment checks.

Files:
- `lyrics.lrc`: raw timed lyrics as provided.
- `lyrics.txt`: pipeline input; timestamps removed and parenthetical sung lines unwrapped so `s03b` does not discard them as stage directions.
- `reference_timestamps.json`: line-start reference for `s08_validate.py` drift checks.

Source stems are not stored here. Use the user-provided `Inner Beast Stems.zip` with:
- `0 Lead Vocals.mp3` + `1 Backing Vocals.mp3` -> `vocals.wav`
- `2 Drums.mp3` + `3 Bass.mp3` + `4 Guitar.mp3` + `5 Synth.mp3` + `6 Other.mp3` -> `instrumental.wav`

Note: raw LRC has `[03:25.100]`; the JSON normalizes that to `205.10` seconds.
