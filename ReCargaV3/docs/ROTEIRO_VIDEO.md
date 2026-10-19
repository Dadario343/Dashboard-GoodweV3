# 🎬 Roteiro do vídeo técnico (até 5 minutos)

Publique no YouTube como **não listado**. Use Chrome ou Edge.

## Antes de gravar
1. Rode `python app/server.py` (abre em `localhost:5000`).
2. Deixe duas abas abertas: o dashboard e o README no GitHub (rolado até o diagrama de arquitetura).
3. No dashboard, clique em **↺ Reiniciar** e marque a caixa **voz**.

---

### Cena 1 · Abertura (0:00–0:25)
**Tela:** dashboard aberto, parado no topo.
**Fala:** "Olá, somos a equipe do ReCarga. O desafio da GoodWe pede uma solução que integre geração, armazenamento e uso de energia renovável com monitoramento inteligente. A nossa aplicação é para recarga de veículos elétricos em um estacionamento com energia solar e bateria."

### Cena 2 · Arquitetura (0:25–1:05)
**Tela:** aba do README, diagrama de arquitetura. Passe o cursor pelos blocos enquanto fala.
**Fala:** "Os painéis de 30 kWp alimentam um inversor híbrido GoodWe da série ET, com bateria de lítio da linha Lynx. A energia vai para um barramento com os carregadores. Um sensor Hall mede a corrente de cada vaga e um ESP32 envia o dado ao nosso software em Python. Um ponto importante: o hardware é simulado pelo nosso motor, mas o software é real. Temos um adaptador da biblioteca goodwe, que permite trocar a simulação por dados de um inversor real."

### Cena 3 · Meio-dia: geração e armazenamento (1:05–1:55)
**Tela:**
1. Clique em **Auto (IA)**.
2. Clique em **10×** e espere o relógio chegar a uns **11h** (uns 8 segundos).
3. Clique em **1×**.
4. Mostre o **Fluxo de energia**, o card **Geração renovável** (bateria em 100%) e a barra do barramento.

**Fala:** "São quase meio-dia. O fluxo de energia mostra o sol alimentando os carregadores, a bateria já está cheia e o excedente é injetado na rede. Repare na barra do barramento: a rede contratada é de 40 amperes, mas a geração local amplia a capacidade disponível, até o limite físico de 60. O pré-pago tem prioridade e o pós-pago recebe o que sobra."

### Cena 4 · Diferencial 1: IA preditiva na ponta (1:55–2:50)
**Tela:**
1. Clique em **17h** e depois em **3×**.
2. Mostre o card **Decisões do otimizador**.
3. Quando o relógio passar das 18h, mostre o fluxo (bateria descarregando) e o gráfico **Origem da energia**.
4. Clique em **1×**.

**Fala:** "Aqui está o primeiro diferencial. O horário de ponta, das 18 às 21 horas, tem tarifa três vezes mais cara. O otimizador prevê essa demanda e reserva a bateria antes dela, e este painel explica a decisão em texto. Às 18 horas a bateria assume e a compra de energia da rede cai para zero. No gráfico dá para ver a bateria em verde-água substituindo a rede."

### Cena 5 · Comparação com o modo de referência (2:50–3:20)
**Tela:** ainda na ponta, clique em **Só rede**, mostre o fluxo (rede alta, bateria parada) e volte para **Auto (IA)**. Mostre o card **Impacto da sessão**.
**Fala:** "Para comparar, no modo só rede, sem solar nem bateria, toda a energia vem da rede na tarifa de ponta. Voltando ao modo Auto, o card de impacto mostra a parcela renovável, o CO₂ evitado e a economia em reais."

### Cena 6 · Diferencial 2: proteção (3:20–3:45)
**Tela:** clique em **⚡ simular falha no sensor** na vaga 1, espere uns 3 segundos e mostre o card **Proteção e alertas**.
**Fala:** "O segundo diferencial é a proteção. Se o sensor Hall indica corrente 25% acima da comandada, o sistema desarma a vaga, registra o alerta e redistribui a corrente. As outras vagas continuam funcionando. Nos testes, a leitura normal nunca gerou falso alarme."

### Cena 7 · Diferencial 3: assistente virtual (3:45–4:20)
**Tela:** no card **Assistente virtual**, clique no 🎤 e fale (ou use os botões de sugestão): "como está a bateria", "quanto CO2 evitamos", "desligue a vaga 3", "o que você recomenda". Mostre a vaga 3 desligando.
**Fala:** "O terceiro diferencial é o assistente virtual em português. Eu posso perguntar por voz como está a bateria, quanto CO₂ evitamos, e até comandar o sistema, como desligar uma vaga. Ele também dá recomendações proativas."

### Cena 8 · Resultados (4:20–4:50)
**Tela:** README, tabela de resultados e o gráfico `sim_cenarios.png`.
**Fala:** "Simulamos 30 dias comparando quatro cenários. Com solar e bateria, 78,8% do consumo é renovável e evitamos 384 kg de CO₂. A IA não cria energia, ela a desloca para a ponta, e com isso reduz o custo líquido da rede em 63% e a compra de energia na ponta em 57%. São resultados de simulação, com tarifas ilustrativas."

### Cena 9 · Encerramento (4:50–5:00)
**Tela:** estrutura do repositório no GitHub.
**Fala:** "O projeto tem 17 testes automatizados, documentação completa e ligação com Pensamento Computacional. Obrigado!"

---

## Dicas
- Ensaie uma vez sem gravar. Se passar de 4min50, corte a Cena 5.
- Se o 🎤 falhar, use os botões de sugestão do assistente.
- Os botões **06h / 12h / 17h / 21h** reposicionam o relógio rápido.
- Se a bateria já estiver esgotada na ponta, clique em **17h** de novo para repetir.
