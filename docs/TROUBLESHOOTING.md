# Troubleshooting - MFA Music Karaoke Multilingue

## 1. Letra não bate com o que é cantado / Modelo G2P não achou fonemas
O idioma que está usando (`lang_tag`) pode não estar alinhado corretamente.
**A Solução:** Cheque o arquivo `config/languages.json` e o `work/04_mfa_corpus/target_model.json`. Se o MFA usou um phonoset incorreto como Fallback, a sincronia será perdida.

## 2. Muitos Modelos Ausentes ou Dicionário Falho (OOV)
Neste pipeline a checagem de erros (`QC Report`) avisa sobre durações muito grandes.
Se o idioma escolhido possui palavras fora do dicionário do MFA (`find_oovs` gerou um `oovs.dict` extenso) é recomendável que você edite o script principal `05_mfa_align.ps1` no trecho de alinhamento temporariamente unindo os dicionários. O pipeline usa o G2P padrão quando possível, evite gírias extremas na letra original se estiver com fonética não-latina sem suporte.

## 3. Demucs não instalou ou separação falhou
Rodando com falhas no CMD do conda? A separação de voz exige que o Demucs esteja operante e ativado (`conda activate demucs_env`). 
Não rode o pipeline do zero dentro do conda base; garanta através do `pip show demucs` e das bibliotecas C++ do montreal que os ambientes não se entrelaçaram.

## 4. Onde encontrar novos Modelos MFA para outras línguas?
O MFA Router tenta fazer o match baseado na sua *lang_tag*. Se o CLI `mfa model list acoustic` possuir outro idioma que queira plugar, basta editar livremente o `config/languages.json` mapeando a key `"sua_tag"` para o `acoustic`, `dictionary` e `g2p` correspondente.

## 5. Segmentos (linhas) longas demais no Karaoke ASS
O QC report acusa falhas se `lyrics.txt` vier formatado na gambiarra.
Quebre o `lyrics.txt` e faça uma linha pra cada 6 a 10 palavras. Se o cantor fizer pausas de respiração, use-a como quebra de linha física.
