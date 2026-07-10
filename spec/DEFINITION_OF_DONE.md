# Definition of Done

Portão global. Nada é "pronto" sem passar por tudo isto:

- [ ] Contratos de artefato preservados (schemas em [DATA_DICTIONARY.md](DATA_DICTIONARY.md) intactos, ou o *contract test* atualizado junto).
- [ ] Geração de ASS/MP4 continua funcionando (não quebrou `s06`/`s07`).
- [ ] Nenhum export sem passar pelo export gate.
- [ ] Falha produz mensagem clara em `status.json` + `events.jsonl`.
- [ ] Sem preset/efeito hardcoded fora da Style Library (FR-020).
- [ ] Sem aceitar path traversal em ZIP.
- [ ] Nenhum artefato *downstream* apagado sem invalidação registrada.
- [ ] Testes automatizados cobrindo a mudança.
- [ ] Suíte verde:

```bash
pytest tests
```

- [ ] Se mexeu em timing/constante: `test_audio_alignment_contracts.py` atualizado no mesmo commit.
- [ ] Se tem superfície de runtime/UI: exercitada de verdade (rodar `python server.py` e dirigir o fluxo afetado), não só teste.

Ver [TEST_PLAN.md](TEST_PLAN.md) para o detalhe de execução.
