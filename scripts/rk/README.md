# Bancada de animação 2D (roda em `C:\rk`, não daqui)

Estes três scripts são cópia versionada do que roda em `C:\rk`, ao lado da instalação
do ComfyUI. **Não rodam a partir deste repo:** os caminhos são absolutos (`C:\rk\ComfyUI\output`)
e o `smoke_scail.py` e o `loop_pick.py` importam `bench_anime.py` e `gate.py`, que moram lá
e não estão aqui. Estão versionados porque `C:\rk` não tem git e o trabalho se perderia.

- `smoke_scail.py` — gera N quadros com SCAIL-2. Lê do ambiente: `SCAIL_W`, `SCAIL_H`,
  `SCAIL_SEED`, `SCAIL_PREFIX`, `SCAIL_POSITIVE`, `SCAIL_POSE` (driver .mp4 em `ComfyUI/input/`).
- `loop_pick.py` — varre janelas de uma geração e mede a emenda. `--skip 5` descarta a
  rampa de entrada do modelo.
- `make_loop_gif.py` — monta o GIF. `--forward` para driver periódico (mede a emenda antes
  de gravar); sem ele, ping-pong. `--selfcheck` roda o controle negativo do ping-pong.

O que decide qualidade continua sendo a tira de contato, não o número — ver §2.7 do guia.
