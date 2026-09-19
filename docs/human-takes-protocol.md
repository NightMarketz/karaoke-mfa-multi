# Roteiro de coleta: take humano real

Fecha o "Fica aberto" de `docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md`:
> O único dado que não existe: um take humano gravado num microfone de verdade. Todo
> número acima vem do stem do Demucs fazendo papel de take.

Sem esse dado, `VOICE_FRAC`, `VOICE_PAD_MS` (`karaoke/scorer.py`) e os limiares de
`karaoke/onset.py` continuam calibrados contra a separação do Demucs, não contra
microfone + ruído de sala reais. Este roteiro não corrige nada sozinho — ele só
produz o corpo de dados que falta pra decidir se e o que recalibrar.

## O que gravar

Por participante, para cada condição abaixo, 1 take em modo `mimic` (clipe curto,
ref já na biblioteca) e 1 take em modo `karaoke` (um job com pipeline completo
rodado, pra ter `vocals_raw.wav` + `word_timing.json`):

| condição | o que varia | por quê |
|---|---|---|
| `quarto silencioso` | ambiente controlado | baseline — o que os testes sintéticos já assumem |
| `quarto com ruido` | TV/conversa ao fundo | `ENERGY_MIN=0.02` nunca foi calibrado contra ruído de sala |
| `referencia no fone` | jogador ouve no fone, grava no mic do notebook/celular | sem vazamento da referência no take |
| `referencia na caixa` | referência toca alto no ambiente, mic capta a mistura | testa se o take vem contaminado pela própria referência |

Mínimo viável: **3 participantes × 4 condições × 2 modos = 24 takes**. Menos que
isso não dá pra separar "essa pessoa canta esquisito" de "essa condição quebra o
scorer" — mas comece por 1 participante × 4 condições se só houver uma pessoa
disponível agora; já é dado real onde hoje há zero.

## Como gravar

1. Suba o servidor (`python server.py`) e abra `/static/mimic.html`.
2. Escolha `mode` e `ref` como de costume, ouça a referência.
3. Marque **"Salvar este take para pesquisa"**, preencha `participante` (nome ou
   apelido curto) e `condicao` (uma das da tabela acima, sempre com o mesmo texto
   pra agrupar certo depois — a agregação usa o texto exato).
4. Grave e pontue normalmente. O take (wav já convertido) e a nota completa vão
   para `input/human_takes/` (gitignored — nunca sobe pro repo).
5. Repita para cada condição/modo.

Sem marcar a caixa, nada é salvo — o jogo normal (mimic e party) não acumula
arquivo.

## Como analisar

```bash
python scripts/analyze_human_takes.py
```

Imprime média/mediana/min/max de `total`/`melody`/`rhythm`/`attacks` por
condição, com o `n` de takes ao lado de cada número (nunca reporta estatística
de grupo vazio). Ler `input/human_takes/<...>.json` individualmente também
serve — cada arquivo tem `n_onsets_ref`/`n_onsets_take`/`n_matched`, úteis pra
ver se um take específico "quebrou" a contagem de ataques.

## O que procurar nos números

- `quarto com ruido` muito abaixo de `quarto silencioso` no mesmo participante:
  `ENERGY_MIN`/`ONSET_THRESHOLD` estão baixos demais pra sala real.
- `referencia na caixa` com `rhythm`/`attacks` artificialmente ALTOS: a
  referência está vazando pro mic e o take está "copiando" o clique da própria
  referência — sintoma diferente de "o jogador cantou bem".
- `melody` sistematicamente baixo em todo mundo: candidato a erro de oitava do
  pyin (`n_octave_suspect_ref` no JSON de resposta, não salvo no arquivo — pegue
  do log do servidor ou adicione ao `_salva_take_para_pesquisa` se precisar).

Recalibrar `VOICE_FRAC`/`VOICE_PAD_MS`/`ONSET_THRESHOLD` a partir daqui é a
próxima decisão — depende do que os números acima mostrarem, não dá pra
antecipar sem o dado.
