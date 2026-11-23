# Assistente MGC – diagnóstico de avarias

Lê manuais PDF e cruza com os casos já resolvidos pelos técnicos, e **sugere** próximos passos. Não decide nada.

## Como funciona (sem instalar nada nos PCs dos técnicos)

Corre **num único PC** da empresa. Os técnicos só abrem o browser: `http://IP-DO-PC:8501`.

1. Instalar Python 3.11+ (marcar "Add Python to PATH").
2. Copiar `.streamlit/secrets.toml.exemplo` para `.streamlit/secrets.toml` e preencher `PIN_ACESSO` e `GEMINI_API_KEY` (chave criada em https://aistudio.google.com).
3. Copiar os PDFs para a pasta `manuais/`.
4. Duplo clique em `iniciar.bat` (instala as bibliotecas só neste PC) e abrir `http://localhost:8501`.
5. Abrir a porta 8501 na firewall para a rede interna.

## Feedback

Cada resposta tem ✅ Resolveu / 🟡 Em parte / ❌ Não resolveu. Ao avaliar, o técnico escreve a causa real e o que fez. Os casos "Resolveu" passam a fazer parte da pesquisa e ficam em `data/feedback.sqlite3` (exportável em CSV na barra lateral). Este é o dado mais valioso do projeto: faça backup.

## Gemini (privacidade e custos)

- A subscrição Google AI Pro **não** inclui a API. A API obtém-se em Google AI Studio (https://aistudio.google.com), com uma chave própria.
- Existe um tier gratuito, mas nele a Google pode usar os pedidos para melhorar produtos e revisores humanos podem lê-los; os próprios termos desaconselham enviar informação confidencial. Os trechos dos manuais e os casos seriam enviados em cada pergunta. Só use Gemini com o tier **pago** (que não usa os dados para melhorar produtos) e depois de confirmar a política da empresa e as cláusulas dos fabricantes.
- A IA local (Ollama) continua suportada (`LLM_PROVIDER = "ollama"`), mas é lenta sem placa gráfica.
- Dica para durar: o modelo é só uma linha de configuração (`OLLAMA_MODEL` / `GEMINI_MODEL`); não há lista de modelos por nome no código, por isso uma descontinuação não parte a app.

## Testes

`python -m unittest discover -s tests -v` (não precisa de Streamlit nem de PDFs).

## Limites conhecidos

- Esquemas elétricos vetoriais: a IA só lê o **texto** do PDF (legendas, bornes). Não "vê" as ligações desenhadas; o técnico vê a página ao lado com zoom.
- Um modelo local pequeno (7B) responde pior que os modelos grandes. Valide com avarias reais passadas antes de confiar.
- 15 técnicos em simultâneo num modelo local exigem hardware adequado (idealmente placa gráfica); sem GPU, as respostas demoram.
- A tradução da página usa o mesmo modelo; a qualidade depende dele.
