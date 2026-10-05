# Ledger `ponytail:`

Gerado em 2026-09-15 por `/ponytail-debt` sobre `claude/party-game-visual-refresh-gaps-fda867`
(HEAD `6a635f5f`). Só código — as ocorrências em `docs/superpowers/plans/*.md` são cópias dos
mesmos blocos dentro de planos, não dívida própria.

Regenerar: `grep -rnE '(#|//) ?ponytail:' karaoke web server*.py scripts`

| Onde | O que foi simplificado | Teto | Gatilho de upgrade |
| --- | --- | --- | --- |
| `karaoke/bounce.py:71` | retorno do pulso descartado se o próximo onset chega antes | onsets mais densos que `decay` nunca voltam ao tamanho base | **no-trigger** |
| `karaoke/background.py:290` | grafo sem `filename_prefix` devolve 0 e segue | cache não quebra para nós que não salvam arquivo; sintoma vira `outputs` vazio | **no-trigger** — só o `_diagnostico` a jusante fala |
| `karaoke/scorer.py:50` | `VOICE_FRAC = 0.10` fixo (−20 dB de p95) | intro sussurrada abaixo disso é perdida; 0,03–0,20 acham o mesmo início no job real | só um take de mic real recalibra — WIP em `claude/sound-library-party-game-033efd` @ `ebd4a054` |
| `karaoke/scorer.py:54` | limiar 0,10×p95 fica acima de `ENERGY_MIN` | ataque fraco na borda da voz sai com o recorte (ref 163 de 164) | `thr = min(VOICE_FRAC×p95, ENERGY_MIN×pico)` se isso importar |
| `karaoke/scorer.py:60` | pad de 100 ms recua por cima de spike já removido | clique a < ~125 ms da primeira nota fica dentro (medido: gap 100 ms → 0/5 ataques; 150 ms → 5/5) | `t0` não recuar sobre frame que a passada de spikes tirou |
| `web/party.html:97` | guarda `beforeunload` só para notebook | iOS não dispara `beforeunload` | trocar por `sessionStorage` se o jogo for para celular |

**6 markers, 2 with no trigger.** (2026-10-05: `scorer.py:31` e `:243` fechados — melodia por frame no mesmo instante, com niveis de afinacao)

Rot risk: `bounce.py:71` e `background.py:290` nomeiam o teto mas não dizem quando revisitar.
Dois dos três upgrades do scorer são "quando isso importar" — gatilho real, mas subjetivo.
