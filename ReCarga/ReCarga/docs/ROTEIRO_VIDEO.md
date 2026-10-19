# 🎬 Roteiro do vídeo técnico (até 5 minutos)

> Grave a tela com o dashboard aberto (`python app/server.py`) e narre por cima. Publique no YouTube como **não listado**.
> Dica: deixe o navegador em tela cheia (F11) e zoom de 90% para caber o painel inteiro.

| Tempo | Mostrar na tela | O que falar |
| --- | --- | --- |
| **0:00–0:25** | Cabeçalho do dashboard + README (diagrama de arquitetura) | Apresente a equipe e o desafio GoodWe: *integrar geração, armazenamento e uso de energia renovável com monitoramento inteligente para recarga de veículos elétricos.* |
| **0:25–1:05** | Arquitetura (Mermaid/PNG do README) | Painéis 30 kWp → inversor híbrido GoodWe ET + bateria Lynx → barramento → carregadores; sensor Hall + ESP32 medem a corrente; o software calcula e decide. **Diga com clareza que o hardware é simulado** e que o adaptador `goodwe` permite usar dados reais. |
| **1:05–1:50** | Modo **Auto (IA)**, **12h**. Mostrar *Fluxo de energia*, card solar/bateria | O sol cobre os carregadores, a bateria carrega até 100% e o excedente é injetado na rede. Capacidade sobe acima dos 40 A contratados (limite físico de 60 A). Pré-pago tem prioridade. |
| **1:50–2:40** | Botão **17h**, depois deixar rodar até a ponta (use **10×**). Mostrar painel *Decisões do otimizador* e gráfico *Origem da energia* | **Diferencial 1 — IA preditiva:** o sistema prevê a ponta (18h–21h, tarifa 3× maior) e **reserva** a bateria; às 18h a bateria assume e a compra de rede cai a zero. Explique: previsão = EMA da nebulosidade + curva solar. |
| **2:40–3:15** | Trocar para **Só rede** no mesmo horário; voltar a **Auto** | Comparação direta: sem solar nem bateria o custo de ponta é integral. Mostre o card *Impacto da sessão* (renovável %, CO₂, economia, margem). |
| **3:15–3:45** | Clicar **⚡ simular falha no sensor** na vaga 1 | **Diferencial 2 — proteção:** leitura 160% do comando → sobrecorrente → vaga desarmada; as outras vagas continuam. Mostre o alerta em *Proteção e alertas*. |
| **3:45–4:20** | Assistente: *"como está a bateria?"*, *"quanto CO2 evitamos?"*, *"desligue a vaga 3"*, *"o que você recomenda?"* (use o 🎤 e ative **voz**) | **Diferencial 3 — assistente virtual** por voz e texto; o mesmo endpoint serve de base para Alexa/Google. |
| **4:20–4:50** | README: tabela de resultados e gráfico `sim_cenarios.png` | **Resultados (30 dias simulados):** 78,8% renovável, 384 kg de CO₂ evitados, custo líquido da rede −63% e compra na ponta −57% com a IA vs. autoconsumo. Cite que a IA **desloca** energia, não a cria. |
| **4:50–5:00** | Estrutura do repositório / testes (`python -m unittest`) | 17 testes automatizados, código organizado, ligação com Pensamento Computacional. Encerramento. |

## Checklist antes de gravar
- [ ] `python -m unittest discover -s tests -v` → 17 testes OK
- [ ] `python app/server.py` abre em `http://localhost:5000`
- [ ] Clicar **↺ Reiniciar** para começar do zero (06h, modo Auto)
- [ ] Chrome/Edge (necessário para o reconhecimento de voz)
- [ ] Microfone testado; marcar a caixa **voz** para o assistente responder falando
- [ ] Vídeo ≤ 5 min, publicado como **não listado** no YouTube
