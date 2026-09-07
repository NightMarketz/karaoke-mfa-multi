# Fundo de ilustração gerado localmente

Data: 2026-08-25
Branch: `claude/pesquisa-fundos-letras-musicais-e67132`

## Objetivo

Trocar o fundo preto chapado do vídeo de karaokê por **uma ilustração gerada
localmente a partir da letra**, com deriva lenta (Ken Burns) e pulso sutil nos
onsets do instrumental. Sem API paga, sem GPU NVIDIA, sem dependência Python nova.

## Estado atual (medido, não lido)

O Step 09 não roda. Resolvendo cada referência `kpaths.X` contra o módulo real:

| arquivo | acessores usados | ausentes |
|---|---|---|
| `scripts/09_video_rendering.py` (invocado por `run_pipeline.py:123` e `server.py:173`) | 12 | 6 |
| `scripts/08_render_video.py` (órfão — nada o invoca) | 6 | 2 |

Ausentes em 09: `adlibs_json`, `lyrics_txt`, `input_video`, `input_thumb`,
`output_video`, `input_job_dir`.
Ausentes em 08: `final_mixed_audio`, `mixing_dir`.

`karaoke/paths.py` define 31 funções; nenhuma dessas oito. O primeiro ausente é
`kpaths.adlibs_json` em `09_video_rendering.py:392` — 13ª linha executável de
`main()`. O estágio estoura com `AttributeError` ali: **o `karaoke.ass` não é
escrito e o MP4 não é encodado.**

Os 6 acessores de 09 estão ausentes também em `master`, `origin/master`, `main` e
`origin/main` (0/6 nas quatro refs). Não é regressão deste worktree.

## Hardware alvo (medido)

ASUS ROG Flow Z13 GZ302EA · Ryzen AI Max+ 395 (16C/32T) · Radeon 8060S integrada ·
**63,6 GB de RAM unificada** · 270 GB livres. **Sem CUDA** — todo
`torch.cuda.is_available()` no repo retorna `False` nesta máquina.

## Recursos já instalados (reusar, não instalar)

- **ComfyUI Desktop** — app em `C:/Users/Katz/AppData/Local/Programs/ComfyUI`,
  dados em `C:/ComfyUI`. Expõe HTTP API (`POST /prompt`, `GET /history`).
- **`C:/ComfyUI/models/diffusion_models/z_image_turbo_bf16.safetensors`** —
  Z-Image-Turbo, 6,15B, **Apache 2.0**, 4–10 passos.
- Alternativa de estilo: `anima-aesthetic-v1.1.safetensors` (ilustração nativa).
- **Não usar** `flux1-krea-dev_fp8_scaled` — licença FLUX.1-dev é não comercial.
- **Ollama** no PATH, com `qwen3:4b` puxado.

## Arquitetura

```
lyrics.txt ──> Ollama qwen3:4b ──> brief visual (1 parágrafo)
                                        │
                                        v
                         ComfyUI POST /prompt (z_image_turbo)
                                        │
                                        v
                    work/jobs/{id}/08_background/background.png
                                        │
instrumental ──> compute_rms/detect_onsets ──> bounce.txt (sendcmd)
                                        │
                                        v
                     ffmpeg: PNG + sendcmd + subtitles ──> MP4
```

### Componente 1 — `karaoke/paths.py` (reparo)

Só os **6 de `09_video_rendering.py`** — os 2 de `08_render_video.py` morrem com
o arquivo (Componente 4).

Antes de escrever acessor novo, repontar para o que já existe. `lyrics_txt` é o
caso claro: `kpaths.lyrics_path` já está entre os 31 e aponta para a mesma letra —
a chamada muda, `paths.py` não cresce. Verificar o mesmo para os outros cinco
antes de adicionar.

O que sobrar entra seguindo a convenção `job_root(job_id) / ...` dos 31
existentes, apontando para onde os estágios anteriores **já gravam de fato** —
sem inventar layout novo. Mais um acessor genuinamente novo:
`background_png(job_id)` → `work/jobs/{id}/08_background/background.png`.

### Componente 2 — `scripts/08b_background_image.py` (novo)

Convenção de nome segue `03b`/`05c` já existentes. Roda antes do Step 09.

1. Lê `kpaths.lyrics_path(job_id)`.
2. **Brief:** `POST http://127.0.0.1:11434/api/generate` (Ollama, `qwen3:4b`) →
   um parágrafo descrevendo cena, paleta, textura, clima. Estilo ilustração.
3. **Imagem:** `POST http://127.0.0.1:8188/prompt` com o workflow em formato API,
   o brief injetado no nó `CLIPTextEncode` positivo; poll em `/history/{id}`;
   copia o PNG de `C:/ComfyUI/output` para `background_png(job_id)`.
4. Ambas as chamadas com `urllib.request` da stdlib. **Zero dependência nova.**

**Regras fixas do prompt** (não são preferência, são requisito de legibilidade):
- sem texto, letras, palavras ou marca d'água na imagem;
- centro da imagem escuro e limpo — o ASS entra por cima;
- 16:9, lado maior ≤ 1024 (limite da playbook AMD para turbo);
- a letra crua **não** vai para o gerador de imagem, só o brief.

**Cache:** se `background_png(job_id)` já existe, pula tudo e sai 0. Espelha
`03c_gemini_transcribe.py:336`. Re-render não re-espera os ~30s.

**Falha:** ComfyUI fora do ar, Ollama fora do ar, timeout ou PNG ausente → loga o
motivo, **não escreve nada e sai 0**. Fundo é enfeite; nunca derruba o job.

### Componente 3 — `scripts/09_video_rendering.py` (reparo + fundo)

Substituir o bloco de render (linhas 516–551) por:

```
ffmpeg -y -loop 1 -i background.png -i <instrumental> -i <vocals>
  -filter_complex "[1:a][2:a]amix=inputs=2:duration=first[a];
                   [0:v]scale=1408:792,sendcmd=f=bounce.txt,
                        crop=1280:720,format=yuv420p,subtitles='karaoke.ass'[v]"
  -map "[v]" -map "[a]" -c:v libx264 -preset fast -crf 22
  -c:a aac -b:a 192k -t <duração> out.mp4
```

Diferenças em relação ao bloco atual, todas necessárias: `-loop 1` (sem isso uma
imagem estática vira vídeo de 1 frame), `-t <duração>` via `ffprobe`,
`format=yuv420p`, e `scale`→`crop` para dimensões pares e fixas.

Se `background.png` não existir, a primeira entrada volta a ser
`-f lavfi -i color=c=#08090f:s=1280x720` e o `sendcmd` sai da cadeia.

**`bounce.txt`:** gerado em `tempfile`, uma linha por onset, dirigindo `w`/`h`/`x`/`y`
do `crop`. Um filtro só carrega deriva lenta **e** pulso — não empilhar `zoompan`,
dois zooms concorrentes brigam. Amplitude do pulso 2–4%. Onsets vêm de
`compute_rms()` + `detect_onsets()` de `scripts/05c_onset_dtw_align.py:32`,
aplicados ao **instrumental** (a batida está lá, não no vocal).

A sintaxe exata do `sendcmd` é o único item não verificado deste spec — confirmar
no spike antes de escrever o resto.

### Componente 4 — deleção

`scripts/08_render_video.py` sai do repo depois que 09 estiver de pé. Dois
renderizadores quebrados é pior que um funcionando.

## Teste

Um arquivo, `tests/test_background.py`, três asserções:

1. `bounce.txt` tem **uma linha por onset detectado, e a contagem é > 0**. Um
   sendcmd vazio renderiza verde e não faz nada — cardinalidade explícita, não
   `every()` sobre lista vazia.
2. Sem `background.png`, o comando montado contém `color=c=#08090f` e **não**
   contém `sendcmd`.
3. Com `background.png`, contém `-loop 1` e `sendcmd`.

**Controles negativos** (a cerca não vale sem eles):
- zerar a lista de onsets → o teste 1 tem de ficar **vermelho**, não passar;
- apagar o PNG no meio → o vídeo ainda sai, no fundo chapado.

## Fora de escopo

- Várias imagens por música com crossfade — usuário escolheu uma só.
- Detecção de seção (verso/refrão).
- Vídeo de verdade via `wan2.2_i2v` (já instalado; ~27 min/clipe pela AMD).
- Troca do backend de imagem para `stable-diffusion.cpp`+Vulkan — plano B se o
  ComfyUI travar; a chamada é isolada num arquivo, a troca é local.

## Riscos

| risco | mitigação |
|---|---|
| ComfyUI Desktop precisa estar rodando | fallback para fundo chapado; documentar no README |
| ~30s/imagem é alegação da AMD, não medição nesta máquina | spike mede e o número vai para o README |
| ROCm em Strix Halo tem relatos de trava | fallback cobre; plano B é sd.cpp+Vulkan |
| Reparar os acessores pode revelar mais quebras a jusante | rodar um job real ponta a ponta antes de fechar |
| Porta do ComfyUI Desktop pode não ser a 8188 padrão | confirmar no spike; virar constante no topo do `08b` |
