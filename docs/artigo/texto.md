# MIRADOURO: ROTULAGEM AUDITÁVEL DE PONTOS PARA DADOS DE REFERÊNCIA EM VALIDAÇÃO DE MAPAS DE USO E COBERTURA DA TERRA

Hugo Henrique Salis ¹

¹ Meridiano Tecnologia, Belo Horizonte, MG, hugo@meridianotecnologia.com.br

## Resumo

A qualidade da referência é o elo fraco da validação de mapas de uso e cobertura da terra: a interpretação visual é um sensor com ruído, e as boas práticas pedem independência, consistência e rastreabilidade. Este trabalho apresenta o MIRADOURO, ferramenta aberta (Python, MIT) de rotulagem de pontos de referência que coloca essas salvaguardas na própria ferramenta: a classe do mapa e o desenho amostral nunca chegam à interface; os painéis de subsídio (Sentinel-2 sazonal, série NDVI e alta resolução) são pré-computados; a resposta é validada contra o desenho declarado; cada gravação é atômica e auditável; segunda passada cega, consenso e revisão dirigida são modos nativos. No caso de uso, 458 pontos de um mapa Sentinel-2 foram interpretados em 2 h 26 min, com mediana por ponto de 25,8 s a 8,8 s e concordância intra-intérprete de 82,6 % (kappa 0,787) medida pela segunda passada embutida.

**Palavras-chave** — interpretação visual, dados de referência, acurácia temática, software livre, Sentinel-2.

## Abstract

*Reference data quality is the weak link of land-cover map validation: visual interpretation is a noisy sensor, and good practice requires independence, consistency and traceability. MIRADOURO is an open tool (Python, MIT) for labelling reference points that builds these safeguards into the tool: the map class and the sampling design never reach the interface; the supporting panels (seasonal Sentinel-2, NDVI series and high-resolution imagery) are precomputed; answers are validated against the declared design; every write is atomic and auditable; blind second pass, consensus and directed review are native modes. In the use case, 458 points of a Sentinel-2 map were interpreted in 2 h 26 min, with the median per point falling from 25.8 s to 8.8 s and intra-interpreter agreement of 82.6 % (kappa 0.787) from the built-in second pass.*

***Key words*** *— visual interpretation, reference data, thematic accuracy, open-source software, Sentinel-2.*

## 1. INTRODUÇÃO

A avaliação de acurácia de um mapa de uso e cobertura da terra repousa sobre três decisões: o desenho amostral, o desenho de resposta e a análise [1]. Entre elas, o desenho de resposta é o que depende de pessoas: a referência de cada unidade amostral é produzida por interpretação visual de imagens, e essa interpretação é um sensor com ruído. Stehman e Foody [2] colocam a qualidade da referência entre as questões centrais de uma avaliação rigorosa; Shimizu et al. [3] mostram que a variabilidade entre intérpretes vicia as estimativas de área e de variância; Pengra et al. [4] mediram a consistência entre intérpretes num programa operacional e encontraram discordâncias relevantes em classes de transição. As boas práticas derivam daí três exigências: independência, para que o intérprete não veja a classe do mapa nem o estrato que gerou o ponto; consistência, verificada por leituras repetidas às cegas; e rastreabilidade, para que se saiba quem rotulou cada ponto, quando, com que subsídio e em quanto tempo.

Há ferramentas maduras para a coleta de referência. O Collect Earth Online [5] é uma plataforma web com múltiplas fontes de imagem, projetos e questionários; ferramentas abertas sobre o Earth Engine [6, 7] levam a interpretação visual para dentro da plataforma de séries temporais; o AcATaMa [8] é um complemento do QGIS que reúne desenho amostral, rotulagem e estimadores num só fluxo. Em todas, porém, as três exigências dependem da disciplina de quem opera: o mapa pode ser carregado como camada, a coluna do estrato fica visível na tabela de atributos, a segunda leitura é um projeto paralelo e os tempos ficam fora do registro. Nada impede que o protocolo seja seguido; nada garante que o tenha sido.

Este trabalho apresenta o MIRADOURO [9], ferramenta aberta (Python, licença MIT) de interpretação de pontos de referência que desloca essas salvaguardas do protocolo para a construção da ferramenta. Os objetivos são: (i) descrever a arquitetura e as salvaguardas por construção; (ii) demonstrar o uso na referência de 458 pontos da validação de um mapa Sentinel-2 na bacia do Paraopeba, Minas Gerais [10], com eficiência e consistência medidas pela própria ferramenta; (iii) delimitar o que a construção garante e o que continua a cargo do protocolo.

## 2. A FERRAMENTA

**2.1. Arquitetura.** Um projeto é um arquivo declarativo (projeto.yaml) com nome, ano de referência, arquivo de pontos (PLOTID, longitude, latitude e colunas extras), colunas ocultas, legenda (código, nome, rótulo, tecla, cor e descrição de cada classe), campos de resposta e provedores de painéis de subsídio, aqui chamados chips. Três componentes se apoiam nesse contrato: um motor de chips, que pré-computa um painel por ponto e por provedor, com cache versionado (a versão do provedor fica gravada no PNG e um painel alterado regera os chips) e registro de falhas por ponto, sem derrubar o lote; uma interface local no navegador, operada pelo teclado; e os exportadores. O núcleo, o motor e a lógica da interface são cobertos por 245 testes automatizados que rodam sem rede, com integração contínua em Python 3.11 e 3.12.

**2.2. Cegueira por construção.** As colunas ocultas declaradas no projeto, no caso de uso a classe do mapa, o estrato e a faixa de distância ao rio, nunca chegam ao navegador: nem na tela, nem em dica, título ou endereço. Um teste automatizado varre tudo o que a interface receberia e falha se qualquer valor oculto aparecer. A mesma regra vale para a revisão dirigida por lista externa: de um arquivo CSV a ferramenta lê somente a coluna PLOTID; o critério que gerou a lista é descartado na leitura e não chega à interface nem ao arquivo de respostas. Na segunda passada, a primeira resposta nunca é exibida.

**2.3. Subsídio pré-computado.** Três provedores de chips acompanham a ferramenta (Figura 1). O primeiro produz, no Google Earth Engine, composições medianas sem nuvens do Sentinel-2 por estação, em cor verdadeira e em falsa-cor do infravermelho próximo, numa janela de 31 × 31 pixels alinhada à grade UTM de 10 m, de modo que o quadrado desenhado é o pixel que contém o ponto, com a vizinhança 3 × 3 contornada. O segundo traça a série multianual de NDVI do mesmo pixel, com o ano de referência destacado. O terceiro recorta a imagem de alta resolução de um serviço de mapas em um ou mais níveis de zoom, projeta sobre ela a pegada real do pixel de 10 m e recua o zoom onde não há cobertura. Como os painéis são gerados antes da interpretação, todos os pontos recebem o mesmo subsídio, a leitura não depende de rede e o painel é o registro do que o intérprete viu.

![Figura 1. O que o intérprete vê, com os chips de um ponto de demonstração em vegetação nativa (Minas Gerais): (a) Sentinel-2, estação seca, cor verdadeira, e (b) falsa-cor NIR, janela de 310 m alinhada à grade de 10 m, com o pixel alvo (amarelo) e a vizinhança 3 × 3 (branco); (c) imagem de alta resolução com a pegada do pixel; (d) série NDVI do pixel, observações de 2019 a 2025, com o ano de referência sombreado. (a) a (c) são recortes dos chips; (d) foi redesenhado no tamanho de impressão.](docs/artigo/fig1_interprete_dupla.png)

**2.4. Validação da resposta.** Os campos de resposta têm tipo (classe, opção, multiopção, texto com expressão regular, número, booleano), obrigatoriedade e obrigatoriedade condicional a outro campo. No caso de uso, a fonte da decisão é uma multiopção (alta resolução, série NDVI, sazonal), a confirmação do ano pela série NDVI é exigida sempre que a alta resolução foi usada, porque o serviço de mapas não informa a data da imagem, e a classe alternativa é exigida quando a confiança não é alta. A tecla Enter valida, grava e avança; uma resposta incompleta é recusada com a lista do que falta.

**2.5. Auditoria.** Cada gravação reescreve o arquivo de respostas por arquivo temporário e renomeação. Cada resposta carrega intérprete, sessão, instantes de criação e de atualização, número de revisões, versão da ferramenta, SHA-256 do projeto em vigor e metadados da interface: tempo acumulado no ponto, por cronômetro que pausa sem ponto carregado, modo de navegação e provedores ausentes, se houver. A abertura de cada sessão gera um backup rotativo do estado anterior. O relatório de sessão resume progresso, respostas, tempo e mediana por ponto de cada sessão, distribuições dos campos, sinais para a segunda passada, listas dirigidas com seus hashes e a concordância entre passadas.

**2.6. Segunda passada, consenso e revisão dirigida.** O comando de sorteio seleciona os pontos de confiança baixa e uma fração aleatória de controle, com semente derivada do hash do projeto, e persiste a amostra (identificadores, fração, semente, hash do arquivo de origem e data), que não é refeita depois que a segunda passada começa. A segunda passada corre sob outro identificador de intérprete, seja outra pessoa, seja a mesma semanas depois, e grava em arquivo separado. O modo de consenso lista as divergências, mostra as duas respostas lado a lado e grava a decisão com as duas leituras originais e seus intérpretes. O modo dirigido percorre uma lista externa e registra cada confirmação como revisão, mesmo sem mudança de valor, o que torna auditável um "todos mantidos". Os exportadores produzem a tabela plana de referência, com as colunas ocultas reanexadas, e o pacote restaurável do AcATaMa [8]. A Tabela 1 resume as salvaguardas.

Tabela 1. Salvaguardas da interpretação de referência e sua garantia por construção no MIRADOURO.

| Salvaguarda | Mecanismo na ferramenta | O que fica registrado |
|---|---|---|
| Independência do mapa | colunas ocultas nunca enviadas à interface; teste automatizado | lista de colunas ocultas no projeto |
| Cegueira na revisão dirigida | só a coluna PLOTID é lida; critério descartado | arquivo, SHA-256 e tamanho da lista |
| Subsídio uniforme | chips pré-computados, cache versionado | versão do provedor em cada PNG; falhas por ponto |
| Resposta completa | tipos, obrigatoriedade condicional, validação no Enter | resposta normalizada pelo tipo |
| Rastreabilidade | gravação atômica; sessão, tempos, revisões, hashes | metadados por resposta e por sessão |
| Consistência | sorteio persistido, segunda passada cega, consenso | amostra, segunda leitura, decisão com as originais |

## 3. CASO DE USO

**3.1. Projeto.** A referência validou um mapa de uso e cobertura de 2023 a 10 m, com oito classes, de três municípios da bacia do rio Paraopeba, Minas Gerais (2.018 km²), descrito em trabalho companheiro [10]. A amostra tem 50 pontos por classe do mapa (398 pontos, dois estratos com 49) e 60 pontos aleatórios na faixa de 0 a 1 km do rio, 458 ao todo. O estrato, a faixa e o nome da classe do mapa entraram como colunas ocultas. Os 1.374 chips (458 pontos, três provedores) foram gerados sem nenhuma falha.

**3.2. Interpretação.** Um único intérprete leu os 458 pontos em quatro sessões produtivas entre 13 e 15 de setembro de 2026. O tempo de interpretação, somado pelos cronômetros por ponto, foi de 2 h 25 min 37 s. A mediana por ponto caiu de 25,8 s na primeira sessão para 16,0, 11,1 e 8,8 s nas seguintes, e o rendimento subiu de 142 para 247 pontos por hora (Figura 2): a curva de aprendizado ficou registrada sem anotação manual. A confiança foi alta em 395 pontos e média em 63; em 419 pontos (91,5 %) a decisão combinou as três fontes; a alta resolução foi usada em 437 pontos e a cobertura confirmada pela série NDVI em 435 deles.

![Figura 2. Eficiência por sessão na primeira passada do caso de uso: mediana de segundos por ponto, número de respostas (n) e pontos por hora.](docs/artigo/fig2_eficiencia.png)

**3.3. Revisões dirigidas.** Em 23 de setembro, duas listas externas foram percorridas no modo dirigido. A primeira, com 32 pontos selecionados por um critério mantido fora da ferramenta, resultou em 22 classes corrigidas e 10 mantidas; a segunda, com 55 pontos de um estrato, anotou o contexto na observação, sem mudança de classe, com 9 pontos anotados como mosaico de usos. Cada confirmação ficou gravada como revisão, com o hash da lista. A Tabela 2 reúne os números do caso.

Tabela 2. Números do caso de uso, extraídos dos relatórios de sessão e dos metadados gravados pela ferramenta.

| Medida | Valor |
|---|---|
| Pontos; chips gerados; falhas | 458; 1.374; 0 |
| Sessões produtivas; tempo de interpretação | 4; 2 h 25 min 37 s |
| Mediana por ponto, 1ª → 4ª sessão | 25,8 → 8,8 s |
| Confiança alta / média / baixa | 395 / 63 / 0 |
| Revisões dirigidas (pontos; corrigidos) | 32 (22) e 55 (0) |
| Segunda passada cega (pontos; tempo) | 46; 10 min 50 s |
| Concordância intra-intérprete (kappa) | 38/46 = 82,6 % (0,787) |
| Divergências arbitradas; tempo | 8; 2 min 28 s |

**3.4. Segunda passada cega e consenso.** Como nenhuma resposta teve confiança baixa, a segunda passada foi a amostra de controle de 10 %: 46 pontos, lidos pelo mesmo intérprete sob outro identificador em 30 de setembro, 15 a 17 dias depois das leituras originais, em 10 min 50 s. A concordância na classe foi de 38 em 46 (82,6 %; kappa de Cohen 0,787), calculada antes do consenso; sem os 8 pontos que também estavam nas listas dirigidas, com distância temporal de 7 dias, foi de 33 em 38 (86,8 %). As 8 divergências foram arbitradas no modo de consenso em 2 min 28 s; a ferramenta regravou só os 8 registros, com as duas leituras originais guardadas; os outros 450 ficaram idênticos ao backup da sessão. A acurácia do mapa sobre essa referência é reportada em [10].

## 4. DISCUSSÃO

A contribuição está no lugar das salvaguardas. Independência, subsídio uniforme, resposta completa, rastreabilidade e verificação de consistência deixam de ser itens de um protocolo que o operador promete cumprir e passam a ser propriedades verificáveis do sistema: há teste para a cegueira, hash para cada lista e cada projeto, cronômetro para cada ponto e um arquivo de amostra que a ferramenta se recusa a refazer. O caso de uso mostra o que isso rende: a curva de aprendizado, a consistência intra-intérprete e o custo do consenso foram medidos, e a releitura de critério, que num fluxo manual seria uma edição silenciosa, ficou gravada ponto a ponto.

A construção não substitui o protocolo. O desenho amostral e os estimadores [1] continuam fora da ferramenta, que exporta a referência para eles; o desenho de resposta é declarado pelo responsável pelo protocolo, e a ferramenta o aplica sem julgá-lo. A instabilidade de um critério da legenda, visível nas 22 correções da revisão dirigida e em metade das 8 divergências da passada cega, foi registrada pela ferramenta, não evitada por ela: o remédio é a legenda, não o programa.

Três limites merecem registro. O caso é único, com um só intérprete: a consistência medida é intra-observador, e a passada com segundo intérprete, que a ferramenta já suporta, fica para a versão estendida. Os provedores dependem de serviços externos: o Earth Engine, para as composições e a série NDVI, e um serviço de mapas cuja imagem não traz data, mitigada pela confirmação do ano no desenho de resposta. Por fim, a concordância que o relatório de sessão imprime é calculada sobre a classe já arbitrada e, depois do consenso, torna-se circular; o número correto exige reconstruir as leituras originais que o arquivo guarda, o que foi feito fora da ferramenta e entra no roteiro de desenvolvimento, junto com o orquestrador de protocolo.

Em relação ao Collect Earth Online [5] e ao AcATaMa [8], o MIRADOURO não compete na coleta multiusuário nem nos estimadores: ocupa a etapa de rotulagem e propõe que a cegueira, o subsídio e a auditoria sejam garantidos antes de qualquer análise.

## 5. CONCLUSÕES

O MIRADOURO coloca na construção da ferramenta as salvaguardas que as boas práticas atribuem ao protocolo de interpretação de referência: a classe do mapa e o desenho amostral não chegam ao intérprete, o subsídio é pré-computado e uniforme, a resposta é validada contra um desenho declarado, cada gravação é atômica e auditável, e segunda passada, consenso e revisão dirigida são modos nativos com amostra persistida. Numa referência real de 458 pontos, a ferramenta registrou 2 h 26 min de interpretação, uma mediana por ponto que caiu de 25,8 s para 8,8 s e uma concordância intra-intérprete de 82,6 %, tudo sem instrumentação adicional. O que a construção garante é a independência e a rastreabilidade da referência; o que continua com o protocolo é o desenho amostral, a legenda, os estimadores e o intérprete. O projeto declarativo permite aplicar a ferramenta a qualquer legenda e região, e a outras tarefas de rotulagem de pontos, como a produção de amostras de treinamento para classificadores, em que o subsídio uniforme e a trilha de auditoria mitigam o ruído de rótulo [11, 12].

## REFERÊNCIAS

[1] P. Olofsson et al. Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment, v. 148, pp. 42–57, 2014.

[2] S. V. Stehman e G. M. Foody. Key issues in rigorous accuracy assessment of land cover products. Remote Sensing of Environment, v. 231, 111199, 2019.

[3] K. Shimizu et al. Quantifying consistency among interpreters of reference data for estimation of harvest area through visual interpretation of remote sensing data. Forestry, v. 99, n. 3, cpaf077, 2025.

[4] B. W. Pengra et al. Quality control and assessment of interpreter consistency of annual land cover reference data in an operational national monitoring program. Remote Sensing of Environment, v. 238, 111261, 2020.

[5] D. Saah et al. Collect Earth: an online tool for systematic reference data collection in land cover and use applications. Environmental Modelling & Software, v. 118, pp. 166–171, 2019.

[6] E. Akturk. ViitGEE: an open-source tool for visual image interpretation and reference data collection in Google Earth Engine. Earth Science Informatics, v. 18, n. 4, 504, 2025.

[7] T. Zhao et al. An interactive toolkit based on Google Earth Engine for visual interpretation and analysis of land cover and land cover changes. Big Earth Data, v. 10, n. 3, pp. 1929–1953, 2026.

[8] X. C. Llano et al. AcATaMa: a QGIS plugin for accuracy assessment and area estimation. Applied Computing and Geosciences, v. 31, 100389, 2026.

[9] H. H. Salis. MIRADOURO: ferramenta de interpretação de pontos de referência, versão 0.1.0 [software], 2026. https://github.com/hugoh-sig/miradouro.

[10] H. H. Salis. Mapeamento multiescalar da agricultura familiar na bacia do rio Paraopeba (MG): Sentinel-2, análise de vizinhança e MapBiomas. Submetido ao XXII Simpósio Brasileiro de Sensoriamento Remoto, 2027.

[11] Y. Tang et al. Weakly supervised land-cover classification of high-resolution images with low-resolution labels through optimized label refinement. International Journal of Remote Sensing, v. 46, n. 5, pp. 1913–1937, 2025.

[12] J. Sun et al. A Segment Anything Model based weakly supervised learning method for crop mapping using Sentinel-2 time series images. International Journal of Applied Earth Observation and Geoinformation, v. 133, 104085, 2024.
