# Skill Routing

Mapa de gatilho → skill. Fluxo SDD: spec/evidência antes do código (não
"failing test first"). Skills ativas existem hoje; candidatas adiadas estão
marcadas (ver [gap-analysis.md](gap-analysis.md)).

## Mandatory Routing

| Gatilho | Skill | Status |
|---|---|---|
| Path/model/host/porta/render default/hardware/threshold hardcoded, ou centralizar config. | `hardcoded-config-audit` | ativa |
| Entrada/saída de estágio `s01–s08`, nome de artefato, ordem, invalidação, manifest, runner. | `pipeline-stage-contracts` | ativa |
| Timing de palavra, duração mínima, drift, gap, melisma, sustain, snap de pitch, fallback CTC/HubertFA, timing do ASS. | `audio-alignment-audit` | ativa |
| Geração local via Ollama, seleção de modelo, context contract, auditoria de saída local. | `pap-ollama` | ativa |
| Fluxo do Review Wizard (points, issues, risco, preview, export gate). | `review-wizard-qa` | adiada → regra na spec |
| Presets ASS, seção→estilo, aliases, efeitos, semântica de cor. | `karaoke-style-library` | adiada → regra na spec |
| Schema de manifest, validação de hash, proveniência, reuso de artefato, regeneração. | `provenance-artifact-audit` | adiada → use `pipeline-stage-contracts` |
| Auditoria de saída de modelo local do PAP. | `pap-ollama-audit` | adiada → embutida em `pap-ollama` |

## Combination Order

1. SDD primeiro: consulte/escreva a spec + tabela de evidência antes de editar (ver [../../spec/TASK_SPEC_TEMPLATE.md](../../spec/TASK_SPEC_TEMPLATE.md)).
2. Do mais estrutural ao mais estreito: `hardcoded-config-audit` → `pipeline-stage-contracts` → `audio-alignment-audit`.
3. Se um gatilho cai numa skill adiada, aplique a regra da spec correspondente (não crie a skill durante o roteamento).

Exemplos:
- Centralizar render defaults → `hardcoded-config-audit`; se muda nome de artefato/ordem, também `pipeline-stage-contracts`.
- Mudar duração mínima de palavra → `audio-alignment-audit`; se o valor vai pra config compartilhada, também `hardcoded-config-audit`.

## Do Not Use

- Fora das áreas acima (status read-only, listar arquivo, explicação estreita), não use skill.
- Não crie skill durante o roteamento (ver regra de criação no [README.md](README.md) e [gap-analysis.md](gap-analysis.md)).
- Não deixe draft de modelo local pular testes, proveniência ou constraints de alinhamento.
