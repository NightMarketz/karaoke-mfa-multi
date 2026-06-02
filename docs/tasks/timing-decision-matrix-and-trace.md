# Matriz de Decisao e Trilha de Classificacao - Stage 06

## Escopo

- Job auditado: `jobs/202605290001`.
- Fonte estrutural: `analysis.json`.
- Fonte de audio: `vocals.wav`, via `build_audio_activity_map()` e `build_audio_backed_timing()`.
- Fonte de render: `apply_audio_backed_tail_extensions()` e `build_word_highlight_segments()`.
- Observacao sobre silabas: o pipeline atual nao possui silabificacao fonetica completa por palavra. A trilha abaixo usa os `highlight_segments` do renderer como segmentos visuais/silabicos. Quando a palavra nao tem split de sustain, o segmento visual e a palavra inteira.

## Matriz de Decisao

| Entrada / evidencia | Classe | Condicao operacional | Decisao de render | Sugestao ao usuario |
| --- | --- | --- | --- | --- |
| Melisma escrito no texto com cauda vocal ativa anexada | `written_melisma_extension` | Palavra final textual melismatica, tail ativo, `voiced_ratio >= 0.55`, duracao anexada >= 0.20s | Estender a palavra escrita ate o fim da regiao vocal | Reusar a palavra escrita, ex.: `wooow` |
| Palavra final curta com cauda vocal forte antes da proxima linha | `probable_unwritten_vowel_extension` | Tail ativo, `voiced_ratio >= 0.75`, palavra final <= 0.60s, gap seguinte >= 1.20s | Estender a vogal final | `word...`, ex.: `fear...` |
| Cauda vocal moderada, mas insuficiente para render automatico | `possible_lost_tail` | Tail ativo, evidencia moderada ou ambigua | Review-only; preservar linha | Revisar antes de estender |
| Material vocal entre linhas sem texto escrito | `unwritten_interline_melisma` | Tail ativo apos palavra longa/sustentada | Review-only; preservar linha | `[vocalizacao]` |
| Palavra final longa sem atividade vocal suficiente | `false_long_tail` | Tail estrutural longo, evidencia vocal fraca/inativa | Aparar palavra final para duracao conservadora | Legenda vazia; acao `trim_or_realign` |
| Linha com gap interno suspeito e audio suportando palavras | `review_only_backing_or_drift` | Bad gap interno + atividade vocal em palavras da linha | Review-only; nao aplicar extensao/trim automatico na linha | Drift/alignment/backing conforme diagnostico |
| Palavra final depois de grande buraco interno | `final_word_after_alignment_hole` / `alignment_hole` | Gap interno ruim antes de palavra final curta | Review-only; preservar e pedir realinhamento local | Legenda vazia |
| Entrada cedo da proxima frase ou cauda roubada | `early_next_line_entry_drift` | Sobreposicao/entrada curta seguida de gap ruim | Review-only; mover inicio da linha ou revisar cauda anterior | Legenda vazia |
| Gap pequeno entre palavras | `small_gap` | Gap < 0.45s | Absorver visualmente para continuidade do highlight | Nenhuma |
| Gap de respiracao | `breath_gap` | Gap >= 0.45s e < 1.20s | Preservar timing | Nenhuma |
| Gap ruim em secao nao-pausa | `bad_gap` | Gap >= 1.20s fora de secoes musicais | Preservar e diagnosticar | Revisao local |
| Pausa musical/instrumental | `musical_pause` / `instrumental_pause` | Gap longo em secao musical ou interlinha longa | Preservar silencio | Nenhuma |

## Regras de Precedencia

1. Se a linha e `review_only_*`, nenhuma extensao ou trim automatico e aplicado, mesmo que a cauda pareca segura isoladamente.
2. Diagnostico de drift ou alignment hole vence sugestao generica de backing vocal.
3. Classes seguras so alteram o ASS quando nao ha classificacao review-only na linha.
4. Sugestoes como `[vocalizacao]`, `[vocal de apoio]`, `fear...` ou legenda vazia ficam no manifest; elas nao sao injetadas automaticamente no ASS.

## Resumo do Job

- Linhas: 79
- Palavras: 260
- Segmentos visuais/silabicos: 306
- Timing estrutural: `{"inter_word_gaps": {"bad_gap": 5, "breath_gap": 21, "instrumental_pause": 3, "musical_pause": 1, "small_gap": 151}, "tails": {"instrumental_pause": 9, "musical_pause": 15, "none": 34, "possible_lost_tail": 3, "tail_melisma": 4, "tail_vowel_extension": 14}, "vocal_periods": {"melisma": 6, "vowel_extension": 16}}`
- Timing com audio: `{"inter_word_gaps": {"bad_gap": 5, "breath_gap": 21, "instrumental_pause": 3, "musical_pause": 1, "small_gap": 151}, "tails": {"false_long_tail": 1, "instrumental_pause": 4, "musical_pause": 8, "none": 34, "probable_unwritten_vowel_extension": 15, "tail_vowel_extension": 11, "unwritten_interline_melisma": 2, "written_melisma_extension": 4}, "vocal_periods": {"melisma": 6, "vowel_extension": 14}}`
- Extensoes aplicadas no manifest: `18`
- Trims aplicados no manifest: `1`

## Trilha por Frase

| # | Frase | Inicio | Fim original | Fim render | Gaps estruturais | Tail estrutural | Classe audio da linha | Tail audio | Tags | Decisao | Sugestao | Acao |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Hmmmmm | 12.740 | 13.180 | 15.230 |  | tail_melisma |  | written_melisma_extension |  | extend_final_word | Hmmmmm | extend_existing_word |
| 1 | Hmmmmm | 18.280 | 19.160 | 21.170 |  | tail_melisma |  | written_melisma_extension |  | extend_final_word | Hmmmmm | extend_existing_word |
| 2 | Still | 24.480 | 24.780 | 24.780 |  | instrumental_pause |  | instrumental_pause |  | preserve_line |  |  |
| 3 | Breathing | 37.420 | 38.080 | 38.080 |  | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 4 | Running on fumes | 40.660 | 42.600 | 42.600 | Running->on:small_gap(0.08s), on->fumes:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 5 | sealed in the tomb | 43.540 | 47.060 | 47.060 | sealed->in:small_gap(0.12s), in->the:small_gap(0.28s), the->tomb:bad_gap(1.7s) | none | review_only_backing_or_drift | none | final_word_after_alignment_hole | review_only_preserve_line |  | review_local_realign |
| 6 | Dragging my feet | 47.100 | 49.740 | 49.740 | Dragging->my:small_gap(0.1s), my->feet:small_gap(0.2s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 7 | to the beat | 49.780 | 53.320 | 53.320 | to->the:breath_gap(0.62s), the->beat:breath_gap(0.6s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 8 | Taste of the rust | 53.360 | 57.520 | 57.520 | Taste->of:small_gap(0.12s), of->the:small_gap(0.08s), the->rust:breath_gap(0.6s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 9 | Rising above the dust | 57.900 | 63.580 | 63.580 | Rising->above:small_gap(0.28s), above->the:small_gap(0.36s), the->dust:breath_gap(0.64s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 10 | 'Cause I'm still here | 63.620 | 65.300 | 65.300 | 'Cause->I'm:small_gap(0.08s), I'm->still:small_gap(0.14s), still->here:small_gap(0.1s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 11 | Choking on fear | 66.960 | 68.800 | 68.800 | Choking->on:small_gap(0.1s), on->fear:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 12 | About to snap | 69.820 | 70.900 | 76.240 | About->to:small_gap(0.08s), to->snap:small_gap(0.14s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | snap... | extend_final_vowel |
| 13 | So burn it all | 76.240 | 78.820 | 78.820 | So->burn:small_gap(0.14s), burn->it:small_gap(0.04s), it->all:breath_gap(0.68s) | none |  | none |  | preserve_line |  |  |
| 14 | Leave it all behind | 78.860 | 81.500 | 81.500 | Leave->it:small_gap(0.1s), it->all:small_gap(0.24s), all->behind:small_gap(0.06s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 15 | Blinded by the hate | 81.980 | 84.260 | 84.260 | Blinded->by:small_gap(0.08s), by->the:breath_gap(0.53s), the->hate:breath_gap(0.5s) | none |  | none |  | preserve_line |  |  |
| 16 | I'm taking back my fate | 84.760 | 89.180 | 89.180 | I'm->taking:bad_gap(3.02s), taking->back:small_gap(0.12s), back->my:small_gap(0.18s), my->fate:small_gap(0.05s) | none | review_only_backing_or_drift | none | early_next_line_entry_drift | review_only_preserve_line |  | move_line_start_later_or_review_previous_tail |
| 17 | oooohh uuuhhh | 89.240 | 89.940 | 90.670 | oooohh->uuuhhh:small_gap(0.26s) | tail_melisma |  | written_melisma_extension |  | extend_final_word | uuuhhh | extend_existing_word |
| 18 | This iron drinks the life right out of me | 102.940 | 108.600 | 108.600 | This->iron:breath_gap(0.46s), iron->drinks:small_gap(0.16s), drinks->the:small_gap(0.06s), the->life:breath_gap(0.74s), life->right:small_gap(0.2s), right->out:small_gap(0.22s), out->of:small_gap(0.12s), of->me:small_gap(0.24s) | none |  | none |  | preserve_line |  |  |
| 19 | I made this bed of stone | 109.360 | 112.140 | 112.140 | I->made:small_gap(0.23s), made->this:small_gap(0.06s), this->bed:small_gap(0.16s), bed->of:small_gap(0.22s), of->stone:small_gap(0.32s) | none |  | none |  | preserve_line |  |  |
| 20 | now let me sleep | 112.260 | 115.160 | 115.160 | now->let:small_gap(0.38s), let->me:small_gap(0.38s), me->sleep:breath_gap(0.58s) | none |  | none |  | preserve_line |  |  |
| 21 | It tears me down | 115.660 | 117.400 | 117.400 | It->tears:small_gap(0.12s), tears->me:small_gap(0.12s), me->down:small_gap(0.26s) | none |  | none |  | preserve_line |  |  |
| 22 | but feeds the hungry will | 117.520 | 121.400 | 121.400 | but->feeds:small_gap(0.18s), feeds->the:small_gap(0.08s), the->hungry:small_gap(0.24s), hungry->will:breath_gap(0.58s) | none |  | none |  | preserve_line |  |  |
| 23 | It keeps me cool | 121.960 | 123.600 | 123.600 | It->keeps:small_gap(0.12s), keeps->me:small_gap(0.1s), me->cool:small_gap(0.22s) | none |  | none |  | preserve_line |  |  |
| 24 | and keeps me standing still | 123.760 | 127.900 | 128.370 | and->keeps:small_gap(0.24s), keeps->me:small_gap(0.14s), me->standing:breath_gap(0.52s), standing->still:small_gap(0.2s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | still... | extend_final_vowel |
| 25 | A wrench in the gears | 129.200 | 132.100 | 132.100 | A->wrench:small_gap(0.11s), wrench->in:small_gap(0.12s), in->the:small_gap(0.12s), the->gears:small_gap(0.24s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 26 | Grinding the fear | 132.500 | 134.260 | 135.760 | Grinding->the:small_gap(0.04s), the->fear:small_gap(0.24s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | fear... | extend_final_vowel |
| 27 | Out of my mind | 135.760 | 141.140 | 141.140 | Out->of:small_gap(0.08s), of->my:small_gap(0.2s), my->mind:small_gap(0.22s) | tail_vowel_extension |  | unwritten_interline_melisma |  | review_only_preserve_line | [vocalizacao] | review_or_add_non_lyric_vocal_caption |
| 28 | Crossing the line | 141.980 | 142.940 | 147.940 | Crossing->the:small_gap(0.12s), the->line:small_gap(0.14s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | line... | extend_final_vowel |
| 29 | The vision dies | 147.940 | 149.240 | 149.240 | The->vision:small_gap(0.09s), vision->dies:small_gap(0.16s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 30 | I'm going blind | 151.100 | 152.280 | 152.280 | I'm->going:small_gap(0.12s), going->blind:small_gap(0.16s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 31 | But I'm still here | 153.620 | 155.620 | 156.170 | But->I'm:small_gap(0.1s), I'm->still:small_gap(0.1s), still->here:breath_gap(0.58s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | here... | extend_final_vowel |
| 32 | Building up | 157.020 | 159.100 | 159.100 | Building->up:breath_gap(0.56s) | none |  | none |  | preserve_line |  |  |
| 33 | Past the fear | 160.140 | 161.240 | 166.480 | Past->the:small_gap(0.06s), the->fear:small_gap(0.1s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | fear... | extend_final_vowel |
| 34 | Let it burn | 166.480 | 168.560 | 168.560 | Let->it:small_gap(0.26s), it->burn:small_gap(0.12s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 35 | No return | 169.620 | 171.640 | 171.640 | No->return:small_gap(0.34s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 36 | Standing still | 172.680 | 173.740 | 177.920 | Standing->still:small_gap(0.06s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | still... | extend_final_vowel |
| 37 | By sheer force of will | 177.920 | 180.740 | 180.740 | By->sheer:small_gap(0.12s), sheer->force:small_gap(0.22s), force->of:small_gap(0.1s), of->will:small_gap(0.12s) | instrumental_pause |  | instrumental_pause |  | preserve_line |  |  |
| 38 | Piece by piece | 186.220 | 187.900 | 187.900 | Piece->by:small_gap(0.24s), by->piece:small_gap(0.1s) | none |  | none |  | preserve_line |  |  |
| 39 | Bone by bone | 187.980 | 190.040 | 190.040 | Bone->by:small_gap(0.06s), by->bone:small_gap(0.22s) | none |  | none |  | preserve_line |  |  |
| 40 | I build this hell | 190.400 | 192.140 | 192.140 | I->build:small_gap(0.11s), build->this:small_gap(0.08s), this->hell:small_gap(0.08s) | none |  | none |  | preserve_line |  |  |
| 41 | On my own | 192.180 | 193.300 | 193.510 | On->my:small_gap(0.09s), my->own:small_gap(0.16s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | own... | extend_final_vowel |
| 42 | Piece by piece | 198.840 | 200.520 | 200.520 | Piece->by:small_gap(0.08s), by->piece:small_gap(0.1s) | none |  | none |  | preserve_line |  |  |
| 43 | Skin for skin | 200.560 | 202.460 | 203.980 | Skin->for:small_gap(0.1s), for->skin:small_gap(0.26s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | skin... | extend_final_vowel |
| 44 | Let the nightmare | 203.980 | 204.860 | 204.860 | Let->the:small_gap(0.06s), the->nightmare:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 45 | Begin | 204.920 | 205.320 | 206.090 |  | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | Begin... | extend_final_vowel |
| 46 | Oh Fuck | 210.320 | 211.280 | 211.280 | Oh->Fuck:small_gap(0.18s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 47 | It hurts like hell | 213.660 | 215.520 | 215.520 | It->hurts:small_gap(0.06s), hurts->like:small_gap(0.12s), like->hell:small_gap(0.1s) | instrumental_pause |  | instrumental_pause |  | preserve_line |  |  |
| 48 | Cannot catch a breath | 219.540 | 220.820 | 220.820 | Cannot->catch:small_gap(0.18s), catch->a:small_gap(0.08s), a->breath:small_gap(0.11s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 49 | Lights go low | 223.280 | 233.680 | 233.680 | Lights->go:bad_gap(5.28s), go->low:breath_gap(0.48s) | musical_pause | review_only_backing_or_drift | probable_unwritten_vowel_extension | possible_backing_vocal_not_in_lyrics | review_only_preserve_line | [vocal de apoio] | review_backing_vocal_or_local_realign |
| 50 | Pulse comes loose | 235.280 | 236.920 | 236.920 | Pulse->comes:small_gap(0.12s), comes->loose:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 51 | It calls my name | 236.980 | 242.360 | 242.360 | It->calls:bad_gap(1.56s), calls->my:small_gap(0.1s), my->name:bad_gap(2.3s) | none | review_only_backing_or_drift | none | early_next_line_entry_drift | review_only_preserve_line |  | move_line_start_later_or_review_previous_tail |
| 52 | I must refuse | 242.520 | 243.440 | 250.030 | I->must:small_gap(0.07s), must->refuse:small_gap(0.1s) | instrumental_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | refuse... | extend_final_vowel |
| 53 | 'Cause I'm still here | 267.980 | 269.980 | 269.980 | 'Cause->I'm:small_gap(0.12s), I'm->still:small_gap(0.12s), still->here:breath_gap(0.7s) | none |  | none |  | preserve_line |  |  |
| 54 | Breathing through the fear | 271.100 | 272.600 | 272.990 | Breathing->through:small_gap(0.08s), through->the:small_gap(0.06s), the->fear:small_gap(0.2s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | fear... | extend_final_vowel |
| 55 | About to snap | 274.480 | 282.020 | 282.020 | About->to:small_gap(0.04s), to->snap:small_gap(0.11s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 56 | Falcon's call | 282.140 | 284.980 | 284.980 | Falcon's->call:small_gap(0.1s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 57 | Fuck it all | 285.280 | 287.740 | 287.740 | Fuck->it:small_gap(0.16s), it->all:breath_gap(1.14s) | none |  | none |  | preserve_line |  |  |
| 58 | I won't fall | 287.800 | 290.360 | 290.360 | I->won't:small_gap(0.03s), won't->fall:small_gap(0.12s) | tail_vowel_extension |  | tail_vowel_extension |  | preserve_line |  |  |
| 59 | I must carry on | 290.540 | 291.900 | 292.350 | I->must:small_gap(0.01s), must->carry:small_gap(0.06s), carry->on:small_gap(0.28s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | on... | extend_final_vowel |
| 60 | I won't fall | 294.180 | 298.640 | 298.640 | I->won't:small_gap(0.01s), won't->fall:small_gap(0.18s) | tail_vowel_extension |  | unwritten_interline_melisma |  | review_only_preserve_line | [vocalizacao] | review_or_add_non_lyric_vocal_caption |
| 61 | I must carry on | 300.220 | 307.380 | 307.380 | I->must:instrumental_pause(5.99s), must->carry:small_gap(0.04s), carry->on:small_gap(0.14s) | none |  | none |  | preserve_line |  |  |
| 62 | I won't fall | 307.900 | 309.020 | 309.020 | I->won't:small_gap(0.09s), won't->fall:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 63 | for that | 309.160 | 310.340 | 310.340 | for->that:small_gap(0.04s) | none |  | none |  | preserve_line |  |  |
| 64 | I must carry on | 310.920 | 313.540 | 313.540 | I->must:small_gap(0.19s), must->carry:small_gap(0.04s), carry->on:small_gap(0.16s) | none |  | none |  | preserve_line |  |  |
| 65 | I won't fall | 314.160 | 315.260 | 315.260 | I->won't:small_gap(0.15s), won't->fall:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 66 | for that | 315.460 | 316.640 | 316.640 | for->that:small_gap(0.16s) | none |  | none |  | preserve_line |  |  |
| 67 | I must carry on | 317.300 | 319.740 | 319.740 | I->must:small_gap(0.13s), must->carry:small_gap(0.04s), carry->on:small_gap(0.14s) | none |  | none |  | preserve_line |  |  |
| 68 | I won't fall | 320.180 | 321.680 | 321.680 | I->won't:small_gap(0.43s), won't->fall:small_gap(0.12s) | none |  | none |  | preserve_line |  |  |
| 69 | for that | 321.780 | 322.540 | 322.540 | for->that:small_gap(0.04s) | none |  | none |  | preserve_line |  |  |
| 70 | I must carry on | 323.180 | 326.380 | 326.380 | I->must:breath_gap(0.59s), must->carry:small_gap(0.04s), carry->on:breath_gap(0.56s) | none |  | none |  | preserve_line |  |  |
| 71 | I won't fall | 326.480 | 327.740 | 327.740 | I->won't:breath_gap(0.47s), won't->fall:small_gap(0.08s) | none |  | none |  | preserve_line |  |  |
| 72 | for that | 328.080 | 328.560 | 330.970 | for->that:small_gap(0.26s) | musical_pause |  | probable_unwritten_vowel_extension |  | extend_final_word | that... | extend_final_vowel |
| 73 | I must carry on | 331.360 | 332.890 | 332.890 | I->must:small_gap(0.07s), must->carry:small_gap(0.08s), carry->on:breath_gap(0.48s) | none |  | none |  | preserve_line |  |  |
| 74 | I won't fall | 332.980 | 345.480 | 345.480 | I->won't:instrumental_pause(11.25s), won't->fall:small_gap(0.14s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 75 | for that | 346.700 | 347.140 | 347.140 | for->that:small_gap(0.04s) | musical_pause |  | musical_pause |  | preserve_line |  |  |
| 76 | I must carry on | 349.300 | 350.440 | 350.440 | I->must:small_gap(0.05s), must->carry:small_gap(0.06s), carry->on:small_gap(0.16s) | instrumental_pause |  | instrumental_pause |  | preserve_line |  |  |
| 77 | Oooo wooow | 361.720 | 362.520 | 362.780 | Oooo->wooow:small_gap(0.32s) | tail_melisma |  | written_melisma_extension |  | extend_final_word | wooow | extend_existing_word |
| 78 | I must carry on | 362.780 | 378.860 | 373.380 | I->must:instrumental_pause(6.03s), must->carry:musical_pause(2.94s), carry->on:small_gap(0.04s) | tail_vowel_extension |  | false_long_tail |  | trim_final_word_to_minimum |  | trim_or_realign |

## Trilha por Palavra e Segmento Visual/Silabico

Cada tabela abaixo mostra, para cada frase, a decisao da linha e depois cada palavra/segmento usado no karaoke. `Fim render` pode diferir do original quando houve extensao segura ou trim.

### Linha 00 - Hmmmmm

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `written_melisma_extension`
- Sugestao/acao: `Hmmmmm` / `extend_existing_word`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Hmmmmm | 12.740 | 13.180 | 15.230 | written_melisma_extension | 1 | Hmmmmm | normal | 12.740 | 15.230 | 2.490 | derived | active=True, voiced_ratio=1.0, duration=0.44 |

### Linha 01 - Hmmmmm

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `written_melisma_extension`
- Sugestao/acao: `Hmmmmm` / `extend_existing_word`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Hmmmmm | 18.280 | 19.160 | 21.170 | written_melisma_extension | 1 | Hmmmmm | normal | 18.280 | 21.170 | 2.890 | derived | active=True, voiced_ratio=0.911, duration=0.88 |

### Linha 02 - Still

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `instrumental_pause`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Still | 24.480 | 24.780 | 24.780 | instrumental_pause | 1 | Still | normal | 24.480 | 24.780 | 0.300 | derived | active=False, voiced_ratio=0.0, duration=0.3 |

### Linha 03 - Breathing

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Breathing | 37.420 | 38.080 | 38.080 | musical_pause | 1 | Breathing | normal | 37.420 | 38.080 | 0.660 | derived | active=True, voiced_ratio=0.941, duration=0.66 |

### Linha 04 - Running on fumes

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Running | 40.660 | 41.460 | 41.460 |  | 1 | Running | normal | 40.660 | 41.460 | 0.800 | derived | active=True, voiced_ratio=1.0, duration=0.8 |
| 1 | on | 41.540 | 41.680 | 41.680 |  | 1 | on | normal | 41.540 | 41.680 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 2 | fumes | 41.800 | 42.600 | 42.600 | none | 1 | fumes | normal | 41.800 | 42.600 | 0.800 | derived | active=True, voiced_ratio=0.805, duration=0.8 |

### Linha 05 - sealed in the tomb

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `review_only_backing_or_drift`
- Tail audio: `none`
- Tags: `final_word_after_alignment_hole`
- Sugestao/acao: `` / `review_local_realign`
- Diagnostico estrutural: `final_word_after_alignment_hole -> review_local_realignment; alignment_hole -> preserve_gap_and_flag_review`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | sealed | 43.540 | 44.260 | 44.260 |  | 1 | sealed | normal | 43.540 | 44.260 | 0.720 | derived | active=True, voiced_ratio=0.892, duration=0.72 |
| 1 | in | 44.380 | 44.640 | 44.640 |  | 1 | in | normal | 44.380 | 44.640 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 2 | the | 44.920 | 45.240 | 45.240 |  | 1 | the | normal | 44.920 | 45.240 | 0.320 | derived | active=True, voiced_ratio=0.647, duration=0.32 |
| 3 | tomb | 46.940 | 47.060 | 47.060 | none | 1 | tomb | normal | 46.940 | 47.060 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |

### Linha 06 - Dragging my feet

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Dragging | 47.100 | 47.740 | 47.740 |  | 1 | Dragging | normal | 47.100 | 47.740 | 0.640 | derived | active=True, voiced_ratio=1.0, duration=0.64 |
| 1 | my | 47.840 | 47.920 | 47.920 |  | 1 | my | normal | 47.840 | 47.920 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 2 | feet | 48.120 | 49.740 | 49.740 | tail_vowel_extension | 1 | f | consonant_attack | 48.120 | 48.217 | 0.097 | derived | active=True, voiced_ratio=0.829, duration=1.62 |
| 2 | feet | 48.120 | 49.740 | 49.740 | tail_vowel_extension | 2 | ee | sustained_vowel | 48.217 | 49.659 | 1.442 | derived | active=True, voiced_ratio=0.829, duration=1.62 |
| 2 | feet | 48.120 | 49.740 | 49.740 | tail_vowel_extension | 3 | t | consonant_release | 49.659 | 49.740 | 0.081 | derived | active=True, voiced_ratio=0.829, duration=1.62 |

### Linha 07 - to the beat

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | to | 49.780 | 50.020 | 50.020 |  | 1 | to | normal | 49.780 | 50.020 | 0.240 | derived | active=True, voiced_ratio=0.769, duration=0.24 |
| 1 | the | 50.640 | 50.800 | 50.800 |  | 1 | the | normal | 50.640 | 50.800 | 0.160 | derived | active=True, voiced_ratio=1.0, duration=0.16 |
| 2 | beat | 51.400 | 53.320 | 53.320 | tail_vowel_extension | 1 | b | consonant_attack | 51.400 | 51.515 | 0.115 | derived | active=True, voiced_ratio=0.835, duration=1.92 |
| 2 | beat | 51.400 | 53.320 | 53.320 | tail_vowel_extension | 2 | ea | sustained_vowel | 51.515 | 53.224 | 1.709 | derived | active=True, voiced_ratio=0.835, duration=1.92 |
| 2 | beat | 51.400 | 53.320 | 53.320 | tail_vowel_extension | 3 | t | consonant_release | 53.224 | 53.320 | 0.096 | derived | active=True, voiced_ratio=0.835, duration=1.92 |

### Linha 08 - Taste of the rust

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Taste | 53.360 | 53.540 | 53.540 |  | 1 | Taste | normal | 53.360 | 53.540 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 1 | of | 53.660 | 53.800 | 53.800 |  | 1 | of | normal | 53.660 | 53.800 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 2 | the | 53.880 | 53.980 | 53.980 |  | 1 | the | normal | 53.880 | 53.980 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 3 | rust | 54.580 | 57.520 | 57.520 | tail_vowel_extension | 1 | r | consonant_attack | 54.580 | 54.756 | 0.176 | derived | active=True, voiced_ratio=0.993, duration=2.94 |
| 3 | rust | 54.580 | 57.520 | 57.520 | tail_vowel_extension | 2 | u | sustained_vowel | 54.756 | 57.373 | 2.617 | derived | active=True, voiced_ratio=0.993, duration=2.94 |
| 3 | rust | 54.580 | 57.520 | 57.520 | tail_vowel_extension | 3 | st | consonant_release | 57.373 | 57.520 | 0.147 | derived | active=True, voiced_ratio=0.993, duration=2.94 |

### Linha 09 - Rising above the dust

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Rising | 57.900 | 59.080 | 59.080 |  | 1 | Rising | normal | 57.900 | 59.080 | 1.180 | derived | active=True, voiced_ratio=1.0, duration=1.18 |
| 1 | above | 59.360 | 59.960 | 59.960 |  | 1 | above | normal | 59.360 | 59.960 | 0.600 | derived | active=True, voiced_ratio=1.0, duration=0.6 |
| 2 | the | 60.320 | 60.400 | 60.400 |  | 1 | the | normal | 60.320 | 60.400 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 3 | dust | 61.040 | 63.580 | 63.580 | tail_vowel_extension | 1 | d | consonant_attack | 61.040 | 61.192 | 0.152 | derived | active=True, voiced_ratio=0.523, duration=2.54 |
| 3 | dust | 61.040 | 63.580 | 63.580 | tail_vowel_extension | 2 | u | sustained_vowel | 61.192 | 63.453 | 2.261 | derived | active=True, voiced_ratio=0.523, duration=2.54 |
| 3 | dust | 61.040 | 63.580 | 63.580 | tail_vowel_extension | 3 | st | consonant_release | 63.453 | 63.580 | 0.127 | derived | active=True, voiced_ratio=0.523, duration=2.54 |

### Linha 10 - 'Cause I'm still here

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 'Cause | 63.620 | 63.820 | 63.820 |  | 1 | 'Cause | normal | 63.620 | 63.820 | 0.200 | derived | active=True, voiced_ratio=1.0, duration=0.2 |
| 1 | I'm | 63.900 | 64.020 | 64.020 |  | 1 | I'm | normal | 63.900 | 64.020 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |
| 2 | still | 64.160 | 64.480 | 64.480 |  | 1 | still | normal | 64.160 | 64.480 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 3 | here | 64.580 | 65.300 | 65.300 | musical_pause | 1 | here | normal | 64.580 | 65.300 | 0.720 | derived | active=True, voiced_ratio=1.0, duration=0.72 |

### Linha 11 - Choking on fear

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Choking | 66.960 | 67.420 | 67.420 |  | 1 | Choking | normal | 66.960 | 67.420 | 0.460 | derived | active=True, voiced_ratio=1.0, duration=0.46 |
| 1 | on | 67.520 | 67.640 | 67.640 |  | 1 | on | normal | 67.520 | 67.640 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |
| 2 | fear | 67.760 | 68.800 | 68.800 | none | 1 | fear | normal | 67.760 | 68.800 | 1.040 | derived | active=True, voiced_ratio=1.0, duration=1.04 |

### Linha 12 - About to snap

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `snap...` / `extend_final_vowel`
- Diagnostico estrutural: `possible_lost_tail -> extend_final_vowel_candidate`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | About | 69.820 | 70.440 | 70.440 |  | 1 | About | normal | 69.820 | 70.440 | 0.620 | derived | active=True, voiced_ratio=1.0, duration=0.62 |
| 1 | to | 70.520 | 70.580 | 70.580 |  | 1 | to | normal | 70.520 | 70.580 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 2 | snap | 70.720 | 70.900 | 76.240 | probable_unwritten_vowel_extension | 1 | sn | consonant_attack | 70.720 | 70.900 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 2 | snap | 70.720 | 70.900 | 76.240 | probable_unwritten_vowel_extension | 2 | a | sustained_vowel | 70.900 | 76.060 | 5.160 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 2 | snap | 70.720 | 70.900 | 76.240 | probable_unwritten_vowel_extension | 3 | p | consonant_release | 76.060 | 76.240 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |

### Linha 13 - So burn it all

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | So | 76.240 | 76.340 | 76.340 |  | 1 | So | normal | 76.240 | 76.340 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 1 | burn | 76.480 | 76.960 | 76.960 |  | 1 | burn | normal | 76.480 | 76.960 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |
| 2 | it | 77.000 | 77.280 | 77.280 |  | 1 | it | normal | 77.000 | 77.280 | 0.280 | derived | active=True, voiced_ratio=1.0, duration=0.28 |
| 3 | all | 77.960 | 78.820 | 78.820 | none | 1 | all | normal | 77.960 | 78.820 | 0.860 | derived | active=True, voiced_ratio=1.0, duration=0.86 |

### Linha 14 - Leave it all behind

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Leave | 78.860 | 79.260 | 79.260 |  | 1 | Leave | normal | 78.860 | 79.260 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 1 | it | 79.360 | 79.500 | 79.500 |  | 1 | it | normal | 79.360 | 79.500 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 2 | all | 79.740 | 80.000 | 80.000 |  | 1 | all | normal | 79.740 | 80.000 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 3 | behind | 80.060 | 81.500 | 81.500 | tail_vowel_extension | 1 | b | consonant_attack | 80.060 | 80.146 | 0.086 | derived | active=True, voiced_ratio=1.0, duration=1.44 |
| 3 | behind | 80.060 | 81.500 | 81.500 | tail_vowel_extension | 2 | e | sustained_vowel | 80.146 | 81.420 | 1.274 | derived | active=True, voiced_ratio=1.0, duration=1.44 |
| 3 | behind | 80.060 | 81.500 | 81.500 | tail_vowel_extension | 3 | hind | consonant_release | 81.420 | 81.500 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=1.44 |

### Linha 15 - Blinded by the hate

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Blinded | 81.980 | 82.540 | 82.540 |  | 1 | Blinded | normal | 81.980 | 82.540 | 0.560 | derived | active=True, voiced_ratio=1.0, duration=0.56 |
| 1 | by | 82.620 | 82.670 | 82.670 |  | 1 | by | normal | 82.620 | 82.670 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 2 | the | 83.200 | 83.280 | 83.280 |  | 1 | the | normal | 83.200 | 83.280 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 3 | hate | 83.780 | 84.260 | 84.260 | none | 1 | hate | normal | 83.780 | 84.260 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |

### Linha 16 - I'm taking back my fate

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `review_only_backing_or_drift`
- Tail audio: `none`
- Tags: `early_next_line_entry_drift`
- Sugestao/acao: `` / `move_line_start_later_or_review_previous_tail`
- Diagnostico estrutural: `alignment_hole -> preserve_gap_and_flag_review`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I'm | 84.760 | 84.920 | 84.920 |  | 1 | I'm | normal | 84.760 | 84.920 | 0.160 | derived | active=True, voiced_ratio=1.0, duration=0.16 |
| 1 | taking | 87.940 | 88.200 | 88.200 |  | 1 | taking | normal | 87.940 | 88.200 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 2 | back | 88.320 | 88.680 | 88.680 |  | 1 | back | normal | 88.320 | 88.680 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 3 | my | 88.860 | 88.910 | 88.910 |  | 1 | my | normal | 88.860 | 88.910 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 4 | fate | 88.960 | 89.180 | 89.180 | none | 1 | fate | normal | 88.960 | 89.180 | 0.220 | derived | active=True, voiced_ratio=1.0, duration=0.22 |

### Linha 17 - oooohh uuuhhh

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `written_melisma_extension`
- Sugestao/acao: `uuuhhh` / `extend_existing_word`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | oooohh | 89.240 | 89.480 | 89.480 | melisma | 1 | oooohh | normal | 89.240 | 89.480 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |
| 1 | uuuhhh | 89.740 | 89.940 | 90.670 | written_melisma_extension | 1 | uuuhhh | normal | 89.740 | 90.670 | 0.930 | derived | active=True, voiced_ratio=1.0, duration=0.2 |

### Linha 18 - This iron drinks the life right out of me

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | This | 102.940 | 103.280 | 103.280 |  | 1 | This | normal | 102.940 | 103.280 | 0.340 | derived | active=True, voiced_ratio=0.889, duration=0.34 |
| 1 | iron | 103.740 | 103.940 | 103.940 |  | 1 | iron | normal | 103.740 | 103.940 | 0.200 | derived | active=True, voiced_ratio=1.0, duration=0.2 |
| 2 | drinks | 104.100 | 104.840 | 104.840 |  | 1 | drinks | normal | 104.100 | 104.840 | 0.740 | derived | active=True, voiced_ratio=1.0, duration=0.74 |
| 3 | the | 104.900 | 105.000 | 105.000 |  | 1 | the | normal | 104.900 | 105.000 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 4 | life | 105.740 | 106.180 | 106.180 |  | 1 | life | normal | 105.740 | 106.180 | 0.440 | derived | active=True, voiced_ratio=1.0, duration=0.44 |
| 5 | right | 106.380 | 106.900 | 106.900 |  | 1 | right | normal | 106.380 | 106.900 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 6 | out | 107.120 | 107.700 | 107.700 |  | 1 | out | normal | 107.120 | 107.700 | 0.580 | derived | active=True, voiced_ratio=1.0, duration=0.58 |
| 7 | of | 107.820 | 108.240 | 108.240 |  | 1 | of | normal | 107.820 | 108.240 | 0.420 | derived | active=True, voiced_ratio=1.0, duration=0.42 |
| 8 | me | 108.480 | 108.600 | 108.600 | none | 1 | me | normal | 108.480 | 108.600 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |

### Linha 19 - I made this bed of stone

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 109.360 | 109.410 | 109.410 |  | 1 | I | normal | 109.360 | 109.410 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | made | 109.640 | 110.000 | 110.000 |  | 1 | made | normal | 109.640 | 110.000 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | this | 110.060 | 110.280 | 110.280 |  | 1 | this | normal | 110.060 | 110.280 | 0.220 | derived | active=True, voiced_ratio=1.0, duration=0.22 |
| 3 | bed | 110.440 | 110.720 | 110.720 |  | 1 | bed | normal | 110.440 | 110.720 | 0.280 | derived | active=True, voiced_ratio=1.0, duration=0.28 |
| 4 | of | 110.940 | 111.180 | 111.180 |  | 1 | of | normal | 110.940 | 111.180 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |
| 5 | stone | 111.500 | 112.140 | 112.140 | none | 1 | stone | normal | 111.500 | 112.140 | 0.640 | derived | active=True, voiced_ratio=1.0, duration=0.64 |

### Linha 20 - now let me sleep

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | now | 112.260 | 112.820 | 112.820 |  | 1 | now | normal | 112.260 | 112.820 | 0.560 | derived | active=True, voiced_ratio=1.0, duration=0.56 |
| 1 | let | 113.200 | 113.600 | 113.600 |  | 1 | let | normal | 113.200 | 113.600 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 2 | me | 113.980 | 114.120 | 114.120 |  | 1 | me | normal | 113.980 | 114.120 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 3 | sleep | 114.700 | 115.160 | 115.160 | none | 1 | sleep | normal | 114.700 | 115.160 | 0.460 | derived | active=True, voiced_ratio=1.0, duration=0.46 |

### Linha 21 - It tears me down

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | It | 115.660 | 115.820 | 115.820 |  | 1 | It | normal | 115.660 | 115.820 | 0.160 | derived | active=True, voiced_ratio=1.0, duration=0.16 |
| 1 | tears | 115.940 | 116.300 | 116.300 |  | 1 | tears | normal | 115.940 | 116.300 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | me | 116.420 | 116.500 | 116.500 |  | 1 | me | normal | 116.420 | 116.500 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 3 | down | 116.760 | 117.400 | 117.400 | none | 1 | down | normal | 116.760 | 117.400 | 0.640 | derived | active=True, voiced_ratio=1.0, duration=0.64 |

### Linha 22 - but feeds the hungry will

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | but | 117.520 | 117.740 | 117.740 |  | 1 | but | normal | 117.520 | 117.740 | 0.220 | derived | active=True, voiced_ratio=1.0, duration=0.22 |
| 1 | feeds | 117.920 | 119.060 | 119.060 |  | 1 | feeds | normal | 117.920 | 119.060 | 1.140 | derived | active=True, voiced_ratio=1.0, duration=1.14 |
| 2 | the | 119.140 | 119.240 | 119.240 |  | 1 | the | normal | 119.140 | 119.240 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 3 | hungry | 119.480 | 120.500 | 120.500 |  | 1 | hungry | normal | 119.480 | 120.500 | 1.020 | derived | active=True, voiced_ratio=1.0, duration=1.02 |
| 4 | will | 121.080 | 121.400 | 121.400 | none | 1 | will | normal | 121.080 | 121.400 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |

### Linha 23 - It keeps me cool

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | It | 121.960 | 122.060 | 122.060 |  | 1 | It | normal | 121.960 | 122.060 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 1 | keeps | 122.180 | 122.600 | 122.600 |  | 1 | keeps | normal | 122.180 | 122.600 | 0.420 | derived | active=True, voiced_ratio=1.0, duration=0.42 |
| 2 | me | 122.700 | 122.760 | 122.760 |  | 1 | me | normal | 122.700 | 122.760 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 3 | cool | 122.980 | 123.600 | 123.600 | none | 1 | cool | normal | 122.980 | 123.600 | 0.620 | derived | active=True, voiced_ratio=1.0, duration=0.62 |

### Linha 24 - and keeps me standing still

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `still...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | and | 123.760 | 123.980 | 123.980 |  | 1 | and | normal | 123.760 | 123.980 | 0.220 | derived | active=True, voiced_ratio=1.0, duration=0.22 |
| 1 | keeps | 124.220 | 124.940 | 124.940 |  | 1 | keeps | normal | 124.220 | 124.940 | 0.720 | derived | active=True, voiced_ratio=0.973, duration=0.72 |
| 2 | me | 125.080 | 125.180 | 125.180 |  | 1 | me | normal | 125.080 | 125.180 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 3 | standing | 125.700 | 127.120 | 127.120 | vowel_extension | 1 | st | consonant_attack | 125.700 | 125.785 | 0.085 | derived | active=True, voiced_ratio=0.986, duration=1.42 |
| 3 | standing | 125.700 | 127.120 | 127.120 | vowel_extension | 2 | a | sustained_vowel | 125.785 | 127.040 | 1.255 | derived | active=True, voiced_ratio=0.986, duration=1.42 |
| 3 | standing | 125.700 | 127.120 | 127.120 | vowel_extension | 3 | nding | consonant_release | 127.040 | 127.120 | 0.080 | derived | active=True, voiced_ratio=0.986, duration=1.42 |
| 4 | still | 127.320 | 127.900 | 128.370 | probable_unwritten_vowel_extension | 1 | still | normal | 127.320 | 128.370 | 1.050 | derived | active=True, voiced_ratio=0.967, duration=0.58 |

### Linha 25 - A wrench in the gears

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | A | 129.200 | 129.250 | 129.250 |  | 1 | A | normal | 129.200 | 129.250 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | wrench | 129.360 | 129.760 | 129.760 |  | 1 | wrench | normal | 129.360 | 129.760 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 2 | in | 129.880 | 130.060 | 130.060 |  | 1 | in | normal | 129.880 | 130.060 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 3 | the | 130.180 | 130.280 | 130.280 |  | 1 | the | normal | 130.180 | 130.280 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 4 | gears | 130.520 | 132.100 | 132.100 | tail_vowel_extension | 1 | g | consonant_attack | 130.520 | 130.615 | 0.095 | derived | active=True, voiced_ratio=1.0, duration=1.58 |
| 4 | gears | 130.520 | 132.100 | 132.100 | tail_vowel_extension | 2 | ea | sustained_vowel | 130.615 | 132.020 | 1.405 | derived | active=True, voiced_ratio=1.0, duration=1.58 |
| 4 | gears | 130.520 | 132.100 | 132.100 | tail_vowel_extension | 3 | rs | consonant_release | 132.020 | 132.100 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=1.58 |

### Linha 26 - Grinding the fear

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `fear...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Grinding | 132.500 | 133.320 | 133.320 |  | 1 | Grinding | normal | 132.500 | 133.320 | 0.820 | derived | active=True, voiced_ratio=1.0, duration=0.82 |
| 1 | the | 133.360 | 133.440 | 133.440 |  | 1 | the | normal | 133.360 | 133.440 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 2 | fear | 133.680 | 134.260 | 135.760 | probable_unwritten_vowel_extension | 1 | f | consonant_attack | 133.680 | 133.805 | 0.125 | derived | active=True, voiced_ratio=1.0, duration=0.58 |
| 2 | fear | 133.680 | 134.260 | 135.760 | probable_unwritten_vowel_extension | 2 | ea | sustained_vowel | 133.805 | 135.656 | 1.851 | derived | active=True, voiced_ratio=1.0, duration=0.58 |
| 2 | fear | 133.680 | 134.260 | 135.760 | probable_unwritten_vowel_extension | 3 | r | consonant_release | 135.656 | 135.760 | 0.104 | derived | active=True, voiced_ratio=1.0, duration=0.58 |

### Linha 27 - Out of my mind

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `none`
- Tail audio: `unwritten_interline_melisma`
- Sugestao/acao: `[vocalizacao]` / `review_or_add_non_lyric_vocal_caption`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Out | 135.760 | 136.120 | 136.120 |  | 1 | Out | normal | 135.760 | 136.120 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 1 | of | 136.200 | 136.260 | 136.260 |  | 1 | of | normal | 136.200 | 136.260 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 2 | my | 136.460 | 136.640 | 136.640 |  | 1 | my | normal | 136.460 | 136.640 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 3 | mind | 136.860 | 141.140 | 141.140 | unwritten_interline_melisma | 1 | m | consonant_attack | 136.860 | 137.040 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=4.28 |
| 3 | mind | 136.860 | 141.140 | 141.140 | unwritten_interline_melisma | 2 | i | sustained_vowel | 137.040 | 140.960 | 3.920 | derived | active=True, voiced_ratio=1.0, duration=4.28 |
| 3 | mind | 136.860 | 141.140 | 141.140 | unwritten_interline_melisma | 3 | nd | consonant_release | 140.960 | 141.140 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=4.28 |

### Linha 28 - Crossing the line

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `line...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Crossing | 141.980 | 142.280 | 142.280 |  | 1 | Crossing | normal | 141.980 | 142.280 | 0.300 | derived | active=True, voiced_ratio=1.0, duration=0.3 |
| 1 | the | 142.400 | 142.540 | 142.540 |  | 1 | the | normal | 142.400 | 142.540 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 2 | line | 142.680 | 142.940 | 147.940 | probable_unwritten_vowel_extension | 1 | l | consonant_attack | 142.680 | 142.860 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 2 | line | 142.680 | 142.940 | 147.940 | probable_unwritten_vowel_extension | 2 | i | sustained_vowel | 142.860 | 147.760 | 4.900 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 2 | line | 142.680 | 142.940 | 147.940 | probable_unwritten_vowel_extension | 3 | ne | consonant_release | 147.760 | 147.940 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.26 |

### Linha 29 - The vision dies

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | The | 147.940 | 147.990 | 147.990 |  | 1 | The | normal | 147.940 | 147.990 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | vision | 148.080 | 148.520 | 148.520 |  | 1 | vision | normal | 148.080 | 148.520 | 0.440 | derived | active=True, voiced_ratio=1.0, duration=0.44 |
| 2 | dies | 148.680 | 149.240 | 149.240 | musical_pause | 1 | dies | normal | 148.680 | 149.240 | 0.560 | derived | active=True, voiced_ratio=1.0, duration=0.56 |

### Linha 30 - I'm going blind

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I'm | 151.100 | 151.160 | 151.160 |  | 1 | I'm | normal | 151.100 | 151.160 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 1 | going | 151.280 | 151.640 | 151.640 |  | 1 | going | normal | 151.280 | 151.640 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | blind | 151.800 | 152.280 | 152.280 | musical_pause | 1 | blind | normal | 151.800 | 152.280 | 0.480 | derived | active=True, voiced_ratio=0.92, duration=0.48 |

### Linha 31 - But I'm still here

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `here...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | But | 153.620 | 153.860 | 153.860 |  | 1 | But | normal | 153.620 | 153.860 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |
| 1 | I'm | 153.960 | 154.080 | 154.080 |  | 1 | I'm | normal | 153.960 | 154.080 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |
| 2 | still | 154.180 | 154.460 | 154.460 |  | 1 | still | normal | 154.180 | 154.460 | 0.280 | derived | active=True, voiced_ratio=1.0, duration=0.28 |
| 3 | here | 155.040 | 155.620 | 156.170 | probable_unwritten_vowel_extension | 1 | here | normal | 155.040 | 156.170 | 1.130 | derived | active=True, voiced_ratio=1.0, duration=0.58 |

### Linha 32 - Building up

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Building | 157.020 | 157.800 | 157.800 |  | 1 | Building | normal | 157.020 | 157.800 | 0.780 | derived | active=True, voiced_ratio=1.0, duration=0.78 |
| 1 | up | 158.360 | 159.100 | 159.100 | none | 1 | up | normal | 158.360 | 159.100 | 0.740 | derived | active=True, voiced_ratio=1.0, duration=0.74 |

### Linha 33 - Past the fear

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `fear...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Past | 160.140 | 160.480 | 160.480 |  | 1 | Past | normal | 160.140 | 160.480 | 0.340 | derived | active=True, voiced_ratio=0.944, duration=0.34 |
| 1 | the | 160.540 | 160.620 | 160.620 |  | 1 | the | normal | 160.540 | 160.620 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 2 | fear | 160.720 | 161.240 | 166.480 | probable_unwritten_vowel_extension | 1 | f | consonant_attack | 160.720 | 160.900 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | fear | 160.720 | 161.240 | 166.480 | probable_unwritten_vowel_extension | 2 | ea | sustained_vowel | 160.900 | 166.300 | 5.400 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | fear | 160.720 | 161.240 | 166.480 | probable_unwritten_vowel_extension | 3 | r | consonant_release | 166.300 | 166.480 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.52 |

### Linha 34 - Let it burn

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Let | 166.480 | 166.760 | 166.760 |  | 1 | Let | normal | 166.480 | 166.760 | 0.280 | derived | active=True, voiced_ratio=1.0, duration=0.28 |
| 1 | it | 167.020 | 167.160 | 167.160 |  | 1 | it | normal | 167.020 | 167.160 | 0.140 | derived | active=True, voiced_ratio=0.875, duration=0.14 |
| 2 | burn | 167.280 | 168.560 | 168.560 | tail_vowel_extension | 1 | b | consonant_attack | 167.280 | 167.360 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=1.28 |
| 2 | burn | 167.280 | 168.560 | 168.560 | tail_vowel_extension | 2 | u | sustained_vowel | 167.360 | 168.480 | 1.120 | derived | active=True, voiced_ratio=1.0, duration=1.28 |
| 2 | burn | 167.280 | 168.560 | 168.560 | tail_vowel_extension | 3 | rn | consonant_release | 168.480 | 168.560 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=1.28 |

### Linha 35 - No return

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | No | 169.620 | 169.720 | 169.720 |  | 1 | No | normal | 169.620 | 169.720 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 1 | return | 170.060 | 171.640 | 171.640 | tail_vowel_extension | 1 | r | consonant_attack | 170.060 | 170.155 | 0.095 | derived | active=True, voiced_ratio=0.975, duration=1.58 |
| 1 | return | 170.060 | 171.640 | 171.640 | tail_vowel_extension | 2 | e | sustained_vowel | 170.155 | 171.560 | 1.405 | derived | active=True, voiced_ratio=0.975, duration=1.58 |
| 1 | return | 170.060 | 171.640 | 171.640 | tail_vowel_extension | 3 | turn | consonant_release | 171.560 | 171.640 | 0.080 | derived | active=True, voiced_ratio=0.975, duration=1.58 |

### Linha 36 - Standing still

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `still...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Standing | 172.680 | 173.300 | 173.300 |  | 1 | Standing | normal | 172.680 | 173.300 | 0.620 | derived | active=True, voiced_ratio=1.0, duration=0.62 |
| 1 | still | 173.360 | 173.740 | 177.920 | probable_unwritten_vowel_extension | 1 | st | consonant_attack | 173.360 | 173.540 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 1 | still | 173.360 | 173.740 | 177.920 | probable_unwritten_vowel_extension | 2 | i | sustained_vowel | 173.540 | 177.740 | 4.200 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 1 | still | 173.360 | 173.740 | 177.920 | probable_unwritten_vowel_extension | 3 | ll | consonant_release | 177.740 | 177.920 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.38 |

### Linha 37 - By sheer force of will

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `instrumental_pause`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | By | 177.920 | 178.160 | 178.160 |  | 1 | By | normal | 177.920 | 178.160 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |
| 1 | sheer | 178.280 | 178.680 | 178.680 |  | 1 | sheer | normal | 178.280 | 178.680 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 2 | force | 178.900 | 179.300 | 179.300 |  | 1 | force | normal | 178.900 | 179.300 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 3 | of | 179.400 | 179.780 | 179.780 |  | 1 | of | normal | 179.400 | 179.780 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 4 | will | 179.900 | 180.740 | 180.740 | instrumental_pause | 1 | will | normal | 179.900 | 180.740 | 0.840 | derived | active=True, voiced_ratio=1.0, duration=0.84 |

### Linha 38 - Piece by piece

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Piece | 186.220 | 186.880 | 186.880 |  | 1 | Piece | normal | 186.220 | 186.880 | 0.660 | derived | active=True, voiced_ratio=0.971, duration=0.66 |
| 1 | by | 187.120 | 187.300 | 187.300 |  | 1 | by | normal | 187.120 | 187.300 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.18 |
| 2 | piece | 187.400 | 187.900 | 187.900 | none | 1 | piece | normal | 187.400 | 187.900 | 0.500 | derived | active=True, voiced_ratio=1.0, duration=0.5 |

### Linha 39 - Bone by bone

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Bone | 187.980 | 188.540 | 188.540 |  | 1 | Bone | normal | 187.980 | 188.540 | 0.560 | derived | active=True, voiced_ratio=0.966, duration=0.56 |
| 1 | by | 188.600 | 189.140 | 189.140 |  | 1 | by | normal | 188.600 | 189.140 | 0.540 | derived | active=True, voiced_ratio=1.0, duration=0.54 |
| 2 | bone | 189.360 | 190.040 | 190.040 | none | 1 | bone | normal | 189.360 | 190.040 | 0.680 | derived | active=True, voiced_ratio=1.0, duration=0.68 |

### Linha 40 - I build this hell

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 190.400 | 190.450 | 190.450 |  | 1 | I | normal | 190.400 | 190.450 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | build | 190.560 | 191.080 | 191.080 |  | 1 | build | normal | 190.560 | 191.080 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | this | 191.160 | 191.680 | 191.680 |  | 1 | this | normal | 191.160 | 191.680 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 3 | hell | 191.760 | 192.140 | 192.140 | none | 1 | hell | normal | 191.760 | 192.140 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |

### Linha 41 - On my own

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `own...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | On | 192.180 | 192.230 | 192.230 |  | 1 | On | normal | 192.180 | 192.230 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | my | 192.320 | 192.680 | 192.680 |  | 1 | my | normal | 192.320 | 192.680 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | own | 192.840 | 193.300 | 193.510 | probable_unwritten_vowel_extension | 1 | own | normal | 192.840 | 193.510 | 0.670 | derived | active=True, voiced_ratio=1.0, duration=0.46 |

### Linha 42 - Piece by piece

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Piece | 198.840 | 199.340 | 199.340 |  | 1 | Piece | normal | 198.840 | 199.340 | 0.500 | derived | active=True, voiced_ratio=1.0, duration=0.5 |
| 1 | by | 199.420 | 199.920 | 199.920 |  | 1 | by | normal | 199.420 | 199.920 | 0.500 | derived | active=True, voiced_ratio=0.923, duration=0.5 |
| 2 | piece | 200.020 | 200.520 | 200.520 | none | 1 | piece | normal | 200.020 | 200.520 | 0.500 | derived | active=True, voiced_ratio=1.0, duration=0.5 |

### Linha 43 - Skin for skin

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `skin...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Skin | 200.560 | 201.100 | 201.100 |  | 1 | Skin | normal | 200.560 | 201.100 | 0.540 | derived | active=True, voiced_ratio=1.0, duration=0.54 |
| 1 | for | 201.200 | 201.660 | 201.660 |  | 1 | for | normal | 201.200 | 201.660 | 0.460 | derived | active=True, voiced_ratio=1.0, duration=0.46 |
| 2 | skin | 201.920 | 202.460 | 203.980 | probable_unwritten_vowel_extension | 1 | sk | consonant_attack | 201.920 | 202.044 | 0.124 | derived | active=True, voiced_ratio=1.0, duration=0.54 |
| 2 | skin | 201.920 | 202.460 | 203.980 | probable_unwritten_vowel_extension | 2 | i | sustained_vowel | 202.044 | 203.877 | 1.833 | derived | active=True, voiced_ratio=1.0, duration=0.54 |
| 2 | skin | 201.920 | 202.460 | 203.980 | probable_unwritten_vowel_extension | 3 | n | consonant_release | 203.877 | 203.980 | 0.103 | derived | active=True, voiced_ratio=1.0, duration=0.54 |

### Linha 44 - Let the nightmare

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Let | 203.980 | 204.120 | 204.120 |  | 1 | Let | normal | 203.980 | 204.120 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 1 | the | 204.180 | 204.260 | 204.260 |  | 1 | the | normal | 204.180 | 204.260 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 2 | nightmare | 204.380 | 204.860 | 204.860 | none | 1 | nightmare | normal | 204.380 | 204.860 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |

### Linha 45 - Begin

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `Begin...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Begin | 204.920 | 205.320 | 206.090 | probable_unwritten_vowel_extension | 1 | Begin | normal | 204.920 | 206.090 | 1.170 | derived | active=True, voiced_ratio=1.0, duration=0.4 |

### Linha 46 - Oh Fuck

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Oh | 210.320 | 210.440 | 210.440 |  | 1 | Oh | normal | 210.320 | 210.440 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |
| 1 | Fuck | 210.620 | 211.280 | 211.280 | musical_pause | 1 | Fuck | normal | 210.620 | 211.280 | 0.660 | derived | active=True, voiced_ratio=0.912, duration=0.66 |

### Linha 47 - It hurts like hell

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `instrumental_pause`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | It | 213.660 | 213.760 | 213.760 |  | 1 | It | normal | 213.660 | 213.760 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 1 | hurts | 213.820 | 214.140 | 214.140 |  | 1 | hurts | normal | 213.820 | 214.140 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 2 | like | 214.260 | 214.500 | 214.500 |  | 1 | like | normal | 214.260 | 214.500 | 0.240 | derived | active=True, voiced_ratio=0.923, duration=0.24 |
| 3 | hell | 214.600 | 215.520 | 215.520 | instrumental_pause | 1 | hell | normal | 214.600 | 215.520 | 0.920 | derived | active=True, voiced_ratio=0.851, duration=0.92 |

### Linha 48 - Cannot catch a breath

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Cannot | 219.540 | 219.800 | 219.800 |  | 1 | Cannot | normal | 219.540 | 219.800 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 1 | catch | 219.980 | 220.220 | 220.220 |  | 1 | catch | normal | 219.980 | 220.220 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |
| 2 | a | 220.300 | 220.350 | 220.350 |  | 1 | a | normal | 220.300 | 220.350 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 3 | breath | 220.460 | 220.820 | 220.820 | musical_pause | 1 | breath | normal | 220.460 | 220.820 | 0.360 | derived | active=True, voiced_ratio=1.0, duration=0.36 |

### Linha 49 - Lights go low

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `review_only_backing_or_drift`
- Tail audio: `probable_unwritten_vowel_extension`
- Tags: `possible_backing_vocal_not_in_lyrics`
- Sugestao/acao: `[vocal de apoio]` / `review_backing_vocal_or_local_realign`
- Diagnostico estrutural: `suspect_vocal_drift -> local_realignment_review; alignment_hole -> preserve_gap_and_flag_review`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Lights | 223.280 | 227.240 | 227.240 | vowel_extension | 1 | L | consonant_attack | 223.280 | 223.460 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=3.96 |
| 0 | Lights | 223.280 | 227.240 | 227.240 | vowel_extension | 2 | i | sustained_vowel | 223.460 | 227.060 | 3.600 | derived | active=True, voiced_ratio=1.0, duration=3.96 |
| 0 | Lights | 223.280 | 227.240 | 227.240 | vowel_extension | 3 | ghts | consonant_release | 227.060 | 227.240 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=3.96 |
| 1 | go | 232.520 | 232.640 | 232.640 |  | 1 | go | normal | 232.520 | 232.640 | 0.120 | derived | active=True, voiced_ratio=1.0, duration=0.12 |
| 2 | low | 233.120 | 233.680 | 233.680 | probable_unwritten_vowel_extension | 1 | low | normal | 233.120 | 233.680 | 0.560 | derived | active=True, voiced_ratio=1.0, duration=0.56 |

### Linha 50 - Pulse comes loose

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Pulse | 235.280 | 235.680 | 235.680 |  | 1 | Pulse | normal | 235.280 | 235.680 | 0.400 | derived | active=True, voiced_ratio=0.857, duration=0.4 |
| 1 | comes | 235.800 | 236.500 | 236.500 |  | 1 | comes | normal | 235.800 | 236.500 | 0.700 | derived | active=True, voiced_ratio=1.0, duration=0.7 |
| 2 | loose | 236.620 | 236.920 | 236.920 | none | 1 | loose | normal | 236.620 | 236.920 | 0.300 | derived | active=True, voiced_ratio=0.938, duration=0.3 |

### Linha 51 - It calls my name

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `review_only_backing_or_drift`
- Tail audio: `none`
- Tags: `early_next_line_entry_drift`
- Sugestao/acao: `` / `move_line_start_later_or_review_previous_tail`
- Diagnostico estrutural: `alignment_hole -> preserve_gap_and_flag_review; final_word_after_alignment_hole -> review_local_realignment; alignment_hole -> preserve_gap_and_flag_review`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | It | 236.980 | 237.040 | 237.040 |  | 1 | It | normal | 236.980 | 237.040 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 1 | calls | 238.600 | 238.980 | 238.980 |  | 1 | calls | normal | 238.600 | 238.980 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 2 | my | 239.080 | 239.740 | 239.740 |  | 1 | my | normal | 239.080 | 239.740 | 0.660 | derived | active=True, voiced_ratio=1.0, duration=0.66 |
| 3 | name | 242.040 | 242.360 | 242.360 | none | 1 | name | normal | 242.040 | 242.360 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |

### Linha 52 - I must refuse

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `refuse...` / `extend_final_vowel`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 242.520 | 242.570 | 242.570 |  | 1 | I | normal | 242.520 | 242.570 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 242.640 | 242.980 | 242.980 |  | 1 | must | normal | 242.640 | 242.980 | 0.340 | derived | active=True, voiced_ratio=1.0, duration=0.34 |
| 2 | refuse | 243.080 | 243.440 | 250.030 | probable_unwritten_vowel_extension | 1 | r | consonant_attack | 243.080 | 243.260 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | refuse | 243.080 | 243.440 | 250.030 | probable_unwritten_vowel_extension | 2 | e | sustained_vowel | 243.260 | 249.850 | 6.590 | derived | active=True, voiced_ratio=1.0, duration=0.36 |
| 2 | refuse | 243.080 | 243.440 | 250.030 | probable_unwritten_vowel_extension | 3 | fuse | consonant_release | 249.850 | 250.030 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=0.36 |

### Linha 53 - 'Cause I'm still here

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 'Cause | 267.980 | 268.300 | 268.300 |  | 1 | 'Cause | normal | 267.980 | 268.300 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 1 | I'm | 268.420 | 268.480 | 268.480 |  | 1 | I'm | normal | 268.420 | 268.480 | 0.060 | derived | active=True, voiced_ratio=1.0, duration=0.06 |
| 2 | still | 268.600 | 268.940 | 268.940 |  | 1 | still | normal | 268.600 | 268.940 | 0.340 | derived | active=True, voiced_ratio=1.0, duration=0.34 |
| 3 | here | 269.640 | 269.980 | 269.980 | none | 1 | here | normal | 269.640 | 269.980 | 0.340 | derived | active=True, voiced_ratio=1.0, duration=0.34 |

### Linha 54 - Breathing through the fear

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `fear...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Breathing | 271.100 | 271.440 | 271.440 |  | 1 | Breathing | normal | 271.100 | 271.440 | 0.340 | derived | active=True, voiced_ratio=1.0, duration=0.34 |
| 1 | through | 271.520 | 271.860 | 271.860 |  | 1 | through | normal | 271.520 | 271.860 | 0.340 | derived | active=True, voiced_ratio=1.0, duration=0.34 |
| 2 | the | 271.920 | 272.020 | 272.020 |  | 1 | the | normal | 271.920 | 272.020 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |
| 3 | fear | 272.220 | 272.600 | 272.990 | probable_unwritten_vowel_extension | 1 | fear | normal | 272.220 | 272.990 | 0.770 | derived | active=True, voiced_ratio=0.9, duration=0.38 |

### Linha 55 - About to snap

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | About | 274.480 | 275.220 | 275.220 |  | 1 | About | normal | 274.480 | 275.220 | 0.740 | derived | active=True, voiced_ratio=0.711, duration=0.74 |
| 1 | to | 275.260 | 275.310 | 275.310 |  | 1 | to | normal | 275.260 | 275.310 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 2 | snap | 275.420 | 282.020 | 282.020 | tail_vowel_extension | 1 | sn | consonant_attack | 275.420 | 275.600 | 0.180 | derived | active=True, voiced_ratio=0.997, duration=6.6 |
| 2 | snap | 275.420 | 282.020 | 282.020 | tail_vowel_extension | 2 | a | sustained_vowel | 275.600 | 281.840 | 6.240 | derived | active=True, voiced_ratio=0.997, duration=6.6 |
| 2 | snap | 275.420 | 282.020 | 282.020 | tail_vowel_extension | 3 | p | consonant_release | 281.840 | 282.020 | 0.180 | derived | active=True, voiced_ratio=0.997, duration=6.6 |

### Linha 56 - Falcon's call

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Falcon's | 282.140 | 283.220 | 283.220 |  | 1 | Falcon's | normal | 282.140 | 283.220 | 1.080 | derived | active=True, voiced_ratio=1.0, duration=1.08 |
| 1 | call | 283.320 | 284.980 | 284.980 | tail_vowel_extension | 1 | c | consonant_attack | 283.320 | 283.420 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=1.66 |
| 1 | call | 283.320 | 284.980 | 284.980 | tail_vowel_extension | 2 | a | sustained_vowel | 283.420 | 284.897 | 1.477 | derived | active=True, voiced_ratio=1.0, duration=1.66 |
| 1 | call | 283.320 | 284.980 | 284.980 | tail_vowel_extension | 3 | ll | consonant_release | 284.897 | 284.980 | 0.083 | derived | active=True, voiced_ratio=1.0, duration=1.66 |

### Linha 57 - Fuck it all

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Fuck | 285.280 | 285.880 | 285.880 |  | 1 | Fuck | normal | 285.280 | 285.880 | 0.600 | derived | active=True, voiced_ratio=1.0, duration=0.6 |
| 1 | it | 286.040 | 286.500 | 286.500 |  | 1 | it | normal | 286.040 | 286.500 | 0.460 | derived | active=True, voiced_ratio=1.0, duration=0.46 |
| 2 | all | 287.640 | 287.740 | 287.740 | none | 1 | all | normal | 287.640 | 287.740 | 0.100 | derived | active=True, voiced_ratio=1.0, duration=0.1 |

### Linha 58 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `tail_vowel_extension`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 287.800 | 287.850 | 287.850 |  | 1 | I | normal | 287.800 | 287.850 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 287.880 | 288.100 | 288.100 |  | 1 | won't | normal | 287.880 | 288.100 | 0.220 | derived | active=True, voiced_ratio=1.0, duration=0.22 |
| 2 | fall | 288.220 | 290.360 | 290.360 | tail_vowel_extension | 1 | f | consonant_attack | 288.220 | 288.348 | 0.128 | derived | active=False, voiced_ratio=0.444, duration=2.14 |
| 2 | fall | 288.220 | 290.360 | 290.360 | tail_vowel_extension | 2 | a | sustained_vowel | 288.348 | 290.253 | 1.905 | derived | active=False, voiced_ratio=0.444, duration=2.14 |
| 2 | fall | 288.220 | 290.360 | 290.360 | tail_vowel_extension | 3 | ll | consonant_release | 290.253 | 290.360 | 0.107 | derived | active=False, voiced_ratio=0.444, duration=2.14 |

### Linha 59 - I must carry on

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `on...` / `extend_final_vowel`
- Diagnostico estrutural: `possible_lost_tail -> extend_final_vowel_candidate`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 290.540 | 290.590 | 290.590 |  | 1 | I | normal | 290.540 | 290.590 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 290.600 | 290.760 | 290.760 |  | 1 | must | normal | 290.600 | 290.760 | 0.160 | derived | active=True, voiced_ratio=1.0, duration=0.16 |
| 2 | carry | 290.820 | 291.220 | 291.220 |  | 1 | carry | normal | 290.820 | 291.220 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 3 | on | 291.500 | 291.900 | 292.350 | probable_unwritten_vowel_extension | 1 | on | normal | 291.500 | 292.350 | 0.850 | derived | active=True, voiced_ratio=1.0, duration=0.4 |

### Linha 60 - I won't fall

- Decisao da frase: `review_only_preserve_line`
- Classe audio da linha: `none`
- Tail audio: `unwritten_interline_melisma`
- Sugestao/acao: `[vocalizacao]` / `review_or_add_non_lyric_vocal_caption`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 294.180 | 294.230 | 294.230 |  | 1 | I | normal | 294.180 | 294.230 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 294.240 | 294.520 | 294.520 |  | 1 | won't | normal | 294.240 | 294.520 | 0.280 | derived | active=True, voiced_ratio=1.0, duration=0.28 |
| 2 | fall | 294.700 | 298.640 | 298.640 | unwritten_interline_melisma | 1 | f | consonant_attack | 294.700 | 294.880 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=3.94 |
| 2 | fall | 294.700 | 298.640 | 298.640 | unwritten_interline_melisma | 2 | a | sustained_vowel | 294.880 | 298.460 | 3.580 | derived | active=True, voiced_ratio=1.0, duration=3.94 |
| 2 | fall | 294.700 | 298.640 | 298.640 | unwritten_interline_melisma | 3 | ll | consonant_release | 298.460 | 298.640 | 0.180 | derived | active=True, voiced_ratio=1.0, duration=3.94 |

### Linha 61 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 300.220 | 300.270 | 300.270 |  | 1 | I | normal | 300.220 | 300.270 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 306.260 | 306.580 | 306.580 |  | 1 | must | normal | 306.260 | 306.580 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 2 | carry | 306.620 | 307.000 | 307.000 |  | 1 | carry | normal | 306.620 | 307.000 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 3 | on | 307.140 | 307.380 | 307.380 | none | 1 | on | normal | 307.140 | 307.380 | 0.240 | derived | active=True, voiced_ratio=1.0, duration=0.24 |

### Linha 62 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 307.900 | 307.950 | 307.950 |  | 1 | I | normal | 307.900 | 307.950 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 308.040 | 308.420 | 308.420 |  | 1 | won't | normal | 308.040 | 308.420 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 2 | fall | 308.540 | 309.020 | 309.020 | none | 1 | fall | normal | 308.540 | 309.020 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |

### Linha 63 - for that

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | for | 309.160 | 309.780 | 309.780 |  | 1 | for | normal | 309.160 | 309.780 | 0.620 | derived | active=True, voiced_ratio=1.0, duration=0.62 |
| 1 | that | 309.820 | 310.340 | 310.340 | none | 1 | that | normal | 309.820 | 310.340 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |

### Linha 64 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 310.920 | 310.970 | 310.970 |  | 1 | I | normal | 310.920 | 310.970 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 311.160 | 311.700 | 311.700 |  | 1 | must | normal | 311.160 | 311.700 | 0.540 | derived | active=True, voiced_ratio=1.0, duration=0.54 |
| 2 | carry | 311.740 | 312.880 | 312.880 |  | 1 | carry | normal | 311.740 | 312.880 | 1.140 | derived | active=True, voiced_ratio=1.0, duration=1.14 |
| 3 | on | 313.040 | 313.540 | 313.540 | none | 1 | on | normal | 313.040 | 313.540 | 0.500 | derived | active=True, voiced_ratio=1.0, duration=0.5 |

### Linha 65 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 314.160 | 314.210 | 314.210 |  | 1 | I | normal | 314.160 | 314.210 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 314.360 | 314.740 | 314.740 |  | 1 | won't | normal | 314.360 | 314.740 | 0.380 | derived | active=True, voiced_ratio=1.0, duration=0.38 |
| 2 | fall | 314.860 | 315.260 | 315.260 | none | 1 | fall | normal | 314.860 | 315.260 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |

### Linha 66 - for that

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | for | 315.460 | 315.980 | 315.980 |  | 1 | for | normal | 315.460 | 315.980 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 1 | that | 316.140 | 316.640 | 316.640 | none | 1 | that | normal | 316.140 | 316.640 | 0.500 | derived | active=True, voiced_ratio=1.0, duration=0.5 |

### Linha 67 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 317.300 | 317.350 | 317.350 |  | 1 | I | normal | 317.300 | 317.350 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 317.480 | 318.000 | 318.000 |  | 1 | must | normal | 317.480 | 318.000 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | carry | 318.040 | 319.180 | 319.180 |  | 1 | carry | normal | 318.040 | 319.180 | 1.140 | derived | active=True, voiced_ratio=1.0, duration=1.14 |
| 3 | on | 319.320 | 319.740 | 319.740 | none | 1 | on | normal | 319.320 | 319.740 | 0.420 | derived | active=True, voiced_ratio=1.0, duration=0.42 |

### Linha 68 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 320.180 | 320.230 | 320.230 |  | 1 | I | normal | 320.180 | 320.230 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 320.660 | 321.080 | 321.080 |  | 1 | won't | normal | 320.660 | 321.080 | 0.420 | derived | active=True, voiced_ratio=1.0, duration=0.42 |
| 2 | fall | 321.200 | 321.680 | 321.680 | none | 1 | fall | normal | 321.200 | 321.680 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |

### Linha 69 - for that

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | for | 321.780 | 322.420 | 322.420 |  | 1 | for | normal | 321.780 | 322.420 | 0.640 | derived | active=True, voiced_ratio=1.0, duration=0.64 |
| 1 | that | 322.460 | 322.540 | 322.540 | none | 1 | that | normal | 322.460 | 322.540 | 0.080 | derived | active=True, voiced_ratio=1.0, duration=0.08 |

### Linha 70 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 323.180 | 323.230 | 323.230 |  | 1 | I | normal | 323.180 | 323.230 | 0.050 | derived | active=True, voiced_ratio=0.667, duration=0.05 |
| 1 | must | 323.820 | 324.340 | 324.340 |  | 1 | must | normal | 323.820 | 324.340 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | carry | 324.380 | 325.100 | 325.100 |  | 1 | carry | normal | 324.380 | 325.100 | 0.720 | derived | active=True, voiced_ratio=1.0, duration=0.72 |
| 3 | on | 325.660 | 326.380 | 326.380 | none | 1 | on | normal | 325.660 | 326.380 | 0.720 | derived | active=True, voiced_ratio=1.0, duration=0.72 |

### Linha 71 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 326.480 | 326.530 | 326.530 |  | 1 | I | normal | 326.480 | 326.530 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 327.000 | 327.400 | 327.400 |  | 1 | won't | normal | 327.000 | 327.400 | 0.400 | derived | active=True, voiced_ratio=1.0, duration=0.4 |
| 2 | fall | 327.480 | 327.740 | 327.740 | none | 1 | fall | normal | 327.480 | 327.740 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |

### Linha 72 - for that

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `probable_unwritten_vowel_extension`
- Sugestao/acao: `that...` / `extend_final_vowel`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | for | 328.080 | 328.220 | 328.220 |  | 1 | for | normal | 328.080 | 328.220 | 0.140 | derived | active=True, voiced_ratio=1.0, duration=0.14 |
| 1 | that | 328.480 | 328.560 | 330.970 | probable_unwritten_vowel_extension | 1 | th | consonant_attack | 328.480 | 328.629 | 0.149 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 1 | that | 328.480 | 328.560 | 330.970 | probable_unwritten_vowel_extension | 2 | a | sustained_vowel | 328.629 | 330.846 | 2.217 | derived | active=True, voiced_ratio=1.0, duration=0.08 |
| 1 | that | 328.480 | 328.560 | 330.970 | probable_unwritten_vowel_extension | 3 | t | consonant_release | 330.846 | 330.970 | 0.124 | derived | active=True, voiced_ratio=1.0, duration=0.08 |

### Linha 73 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `none`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 331.360 | 331.410 | 331.410 |  | 1 | I | normal | 331.360 | 331.410 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 331.480 | 331.800 | 331.800 |  | 1 | must | normal | 331.480 | 331.800 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 2 | carry | 331.880 | 332.360 | 332.360 |  | 1 | carry | normal | 331.880 | 332.360 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.48 |
| 3 | on | 332.840 | 332.890 | 332.890 | none | 1 | on | normal | 332.840 | 332.890 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |

### Linha 74 - I won't fall

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 332.980 | 333.030 | 333.030 |  | 1 | I | normal | 332.980 | 333.030 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | won't | 344.280 | 344.660 | 344.660 |  | 1 | won't | normal | 344.280 | 344.660 | 0.380 | derived | active=True, voiced_ratio=0.95, duration=0.38 |
| 2 | fall | 344.800 | 345.480 | 345.480 | musical_pause | 1 | fall | normal | 344.800 | 345.480 | 0.680 | derived | active=True, voiced_ratio=0.514, duration=0.68 |

### Linha 75 - for that

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `musical_pause`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | for | 346.700 | 346.820 | 346.820 |  | 1 | for | normal | 346.700 | 346.820 | 0.120 | derived | active=False, voiced_ratio=0.0, duration=0.12 |
| 1 | that | 346.860 | 347.140 | 347.140 | musical_pause | 1 | that | normal | 346.860 | 347.140 | 0.280 | derived | active=False, voiced_ratio=0.4, duration=0.28 |

### Linha 76 - I must carry on

- Decisao da frase: `preserve_line`
- Classe audio da linha: `none`
- Tail audio: `instrumental_pause`
- Diagnostico estrutural: `possible_lost_tail -> extend_final_vowel_candidate`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 349.300 | 349.350 | 349.350 |  | 1 | I | normal | 349.300 | 349.350 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 349.400 | 349.580 | 349.580 |  | 1 | must | normal | 349.400 | 349.580 | 0.180 | derived | active=True, voiced_ratio=0.8, duration=0.18 |
| 2 | carry | 349.640 | 349.960 | 349.960 |  | 1 | carry | normal | 349.640 | 349.960 | 0.320 | derived | active=True, voiced_ratio=1.0, duration=0.32 |
| 3 | on | 350.120 | 350.440 | 350.440 | instrumental_pause | 1 | on | normal | 350.120 | 350.440 | 0.320 | derived | active=True, voiced_ratio=0.941, duration=0.32 |

### Linha 77 - Oooo wooow

- Decisao da frase: `extend_final_word`
- Classe audio da linha: `none`
- Tail audio: `written_melisma_extension`
- Sugestao/acao: `wooow` / `extend_existing_word`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Oooo | 361.720 | 361.980 | 361.980 | melisma | 1 | Oooo | normal | 361.720 | 361.980 | 0.260 | derived | active=True, voiced_ratio=1.0, duration=0.26 |
| 1 | wooow | 362.300 | 362.520 | 362.780 | written_melisma_extension | 1 | wooow | normal | 362.300 | 362.780 | 0.480 | derived | active=True, voiced_ratio=1.0, duration=0.22 |

### Linha 78 - I must carry on

- Decisao da frase: `trim_final_word_to_minimum`
- Classe audio da linha: `none`
- Tail audio: `false_long_tail`
- Sugestao/acao: `` / `trim_or_realign`
- Diagnostico estrutural: `instrumental_pause -> preserve_silence_gap`

| Palavra # | Palavra | Orig inicio | Orig fim | Render fim | Classe palavra/tail | Segmento # | Segmento | Papel | Seg inicio | Seg fim | Duracao | Fonte | Evidencia de audio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I | 362.780 | 362.830 | 362.830 |  | 1 | I | normal | 362.780 | 362.830 | 0.050 | derived | active=True, voiced_ratio=1.0, duration=0.05 |
| 1 | must | 368.860 | 369.380 | 369.380 |  | 1 | must | normal | 368.860 | 369.380 | 0.520 | derived | active=True, voiced_ratio=1.0, duration=0.52 |
| 2 | carry | 372.320 | 372.740 | 372.740 |  | 1 | carry | normal | 372.320 | 372.740 | 0.420 | derived | active=True, voiced_ratio=1.0, duration=0.42 |
| 3 | on | 372.780 | 378.860 | 373.380 | false_long_tail | 1 | on | normal | 372.780 | 373.380 | 0.600 | derived | active=False, voiced_ratio=0.092, duration=6.08 |

