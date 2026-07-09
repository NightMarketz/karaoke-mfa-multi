# DEFINITION_OF_DONE — Karaoke MFA Multi

## 8.1 DoD global

Uma alteração só está pronta quando:

- [ ] Preserva os contratos de artefatos.
- [ ] Não quebra geração de `output.ass`.
- [ ] Não quebra geração de `output.mp4`.
- [ ] Não permite export sem gate.
- [ ] Registra eventos relevantes.
- [ ] Falha com mensagem clara.
- [ ] Tem testes automatizados.
- [ ] Não introduz hardcode de presets fora da Style Library.
- [ ] Não permite path traversal.
- [ ] Não apaga outputs sem invalidation explícita.
- [ ] Atualiza documentação se contrato mudou.
- [ ] `python -m pytest` passa.

## 8.2 DoD por área

### Upload
- [ ] ZIP seguro.
- [ ] Stems detectados.
- [ ] Letra obrigatória validada.
- [ ] Preset validado antes do job.
- [ ] WAVs materializados no formato padrão.
- [ ] Erros aparecem em `status.json` ou resposta HTTP.

### Pipeline
- [ ] Cada stage lê apenas inputs contratados.
- [ ] Cada stage escreve outputs contratados.
- [ ] Timeouts respeitados.
- [ ] `events.jsonl` atualizado.
- [ ] Artefatos downstream invalidados corretamente.

### ASS
- [ ] Contém `[Script Info]`.
- [ ] Contém `[V4+ Styles]`.
- [ ] Contém `[Events]`.
- [ ] Contém diálogos.
- [ ] Contém tags `\kf`.
- [ ] Manifest inclui inputs, outputs, metrics e hashes.

### Render
- [ ] Valida hash do ASS antes de renderizar.
- [ ] Gera MP4 não vazio.
- [ ] Gera manifest do MP4.
- [ ] Registra codec, duração e hashes.

### Review Wizard
- [ ] Cria `review_wizard.json` se ausente.
- [ ] Cria issues quando necessário.
- [ ] Quality report define estado.
- [ ] Preview approval exige evidência.
- [ ] Artifact change bloqueia export.

### Export Gate
- [ ] Bloqueia sem quality report.
- [ ] Bloqueia se artifact graph mudou.
- [ ] Bloqueia se preview obrigatório não foi aprovado.
- [ ] Libera quando estado é `ready` ou risco aprovado corretamente.
- [ ] Revalida manifests antes de download.
