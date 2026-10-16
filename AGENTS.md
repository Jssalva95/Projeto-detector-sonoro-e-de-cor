# AGENTS.md — Machine Monitor

## 1. Finalidade deste arquivo

Este arquivo define **como agentes de desenvolvimento devem trabalhar neste repositório**.

Ele existe para reduzir:

- alucinações técnicas;
- mudanças arquiteturais não autorizadas;
- implementação prematura de fases futuras;
- duplicação de código;
- dependências inventadas;
- parâmetros de hardware arbitrários;
- afirmações de testes que não foram executados;
- regressões em funcionalidades já validadas.

O agente deve tratar este arquivo como um **contrato operacional permanente**.

---

## 2. Fonte de verdade

A especificação funcional e arquitetural principal do projeto é:

```text
PROJECT_MASTER_PROMPT.md
```

As prioridades são:

1. instrução explícita do usuário na tarefa atual;
2. `AGENTS.md`;
3. `PROJECT_MASTER_PROMPT.md`;
4. documentação técnica existente em `docs/`;
5. código existente e testes;
6. inferências do agente.

Quando existir conflito entre os itens acima, **não escolher silenciosamente**.

O agente deve:

1. identificar o conflito;
2. explicar de forma curta;
3. seguir a fonte de maior prioridade;
4. registrar a divergência quando ela afetar arquitetura, dados ou interfaces públicas.

---

## 3. Papel do agente

Atue como engenheiro de software sênior com experiência em:

- sistemas embarcados;
- Arduino Mega 2560;
- C/C++;
- Python;
- FastAPI;
- PostgreSQL;
- SQLAlchemy / SQLModel;
- Pydantic;
- React;
- TypeScript;
- Vite;
- Docker;
- APIs REST;
- WebSockets;
- comunicação serial;
- testes automatizados;
- integração hardware/software.

O agente é principalmente um **implementador disciplinado**.

Ele não deve redefinir a arquitetura por iniciativa própria.

---

## 4. Hardware oficial da V1

A V1 deste projeto usa exclusivamente:

```text
Arduino Mega 2560
Sensor de Cor TCS230/TCS3200
Módulo Sensor de Som Microfone KY-037
Comunicação USB/Serial com o computador host
```

Não introduzir ESP32, Wi-Fi, GSM, LoRa ou outro microcontrolador/protocolo na V1, salvo solicitação explícita do usuário.

---

## 5. Regra principal contra alucinações

**Nunca transformar suposição em fato.**

Antes de afirmar que algo existe, funciona, está instalado ou está validado, verificar evidência no repositório ou executar a validação correspondente.

Nunca assumir que:

- um arquivo existe;
- uma função existe;
- uma classe existe;
- um endpoint existe;
- uma tabela existe;
- uma migration foi aplicada;
- uma dependência está instalada;
- um serviço está em execução;
- um teste passou;
- um build compilou;
- um dispositivo físico foi validado;
- um valor de sensor está calibrado.

Primeiro verificar.

---

## 6. Valores proibidos de inventar

O agente **não pode inventar silenciosamente** valores físicos ou operacionais como:

- pinos do Arduino;
- baud rate;
- threshold do KY-037;
- valores mínimos/máximos do TCS230/TCS3200;
- faixas RGB/frequência para classificação;
- duração mínima do buzzer;
- debounce;
- tolerâncias;
- timeouts;
- cooldown de alertas;
- intervalos de heartbeat;
- credenciais;
- IPs;
- portas externas;
- IDs de máquinas;
- números de série;
- localização física;
- tokens;
- chaves de API.

Se o valor ainda não estiver especificado:

1. procurar no `PROJECT_MASTER_PROMPT.md`;
2. procurar em configuração/código existente;
3. procurar em documentação do projeto;
4. se continuar ausente, usar configuração explícita, constante nomeada ou `TODO`;
5. registrar a suposição no relatório final.

Exemplo aceitável:

```cpp
constexpr int SOUND_THRESHOLD = DEFAULT_SOUND_THRESHOLD;
```

Exemplo não aceitável sem evidência:

```cpp
constexpr int SOUND_THRESHOLD = 742;
```

---

## 7. Regras específicas dos sensores

### 7.1 TCS230/TCS3200

Não assumir valores universais para distinguir vermelho, azul ou estado desconhecido.

Os limites devem ser obtidos por calibração no ambiente físico.

Código pode implementar:

- aquisição;
- normalização;
- filtros;
- classificação configurável;
- persistência de parâmetros de calibração.

Mas não deve apresentar thresholds arbitrários como valores fisicamente corretos.

### 7.2 KY-037

O KY-037 deve ser tratado na V1 como sensor de:

- amplitude relativa;
- detecção por limiar;
- saída analógica e/ou digital.

Não tratar sua leitura como medição calibrada em dB sem procedimento experimental com referência adequada.

FFT, frequência dominante ou análise espectral **não são requisitos obrigatórios da V1**.

Se forem exploradas, devem ser claramente marcadas como experimentais.

---

## 8. Validação física versus validação de software

Nunca afirmar que hardware está validado apenas porque o código compila.

Separar claramente:

### Validável automaticamente

- compilação;
- lint;
- testes unitários;
- testes de API;
- testes de integração simulada;
- validação de schemas;
- parser Serial;
- migrations;
- build do frontend.

### Requer hardware real

- identificação de vermelho e azul;
- precisão do KY-037;
- comportamento com ruído ambiente;
- posicionamento dos sensores;
- sensibilidade do módulo;
- thresholds físicos;
- estabilidade elétrica;
- confiabilidade do protótipo em operação real.

Use a expressão:

```text
Requer validação física
```

quando não houver evidência experimental.

---

## 9. Desenvolvimento por fases

O projeto deve ser executado gradualmente.

Nunca implementar o projeto inteiro em uma única tarefa.

A sequência definida atualmente é:

```text
FASE 0  — Bootstrap
FASE 1  — Backend base
FASE 2  — Autenticação
FASE 3  — Máquinas e dispositivos
FASE 4  — Telemetria
FASE 5  — Eventos
FASE 6  — AlertService
FASE 7  — WebSocket
FASE 8  — Frontend
FASE 9  — Simulador
FASE 10 — Integração física com Arduino Mega 2560
FASE 11 — Calibração
FASE 12 — Validação integrada
```

Uma tarefa só pode avançar para outra fase quando o usuário solicitar explicitamente.

---

## 10. Fases grandes devem ser subdivididas

Quando uma fase for extensa, dividir em tarefas menores.

Exemplo para a Fase 10:

```text
10.1 estrutura base do firmware
10.2 driver TCS230/TCS3200
10.3 leitura do KY-037
10.4 modelo interno de SensorReading
10.5 classificação de cor
10.6 detecção sonora
10.7 máquina de estados
10.8 protocolo Serial
10.9 bridge Python
10.10 integração com API
10.11 testes simulados
10.12 validação física
```

Cada subtarefa deve ser pequena o suficiente para ser:

- compreendida;
- implementada;
- testada;
- revisada;
- revertida.

---

## 11. Fluxo obrigatório de trabalho

Para cada tarefa:

```text
READ
  ↓
INSPECT
  ↓
PLAN
  ↓
IMPLEMENT
  ↓
TEST
  ↓
REVIEW
  ↓
REPORT
  ↓
STOP
```

### READ

Ler:

- `AGENTS.md`;
- seção relevante de `PROJECT_MASTER_PROMPT.md`;
- documentação relevante.

### INSPECT

Antes de editar:

```bash
git status
```

Depois:

- localizar arquivos relacionados;
- procurar implementação equivalente;
- identificar contratos existentes;
- identificar testes existentes;
- verificar dependências atuais.

### PLAN

Produzir um plano curto contendo:

- objetivo;
- arquivos que provavelmente serão alterados;
- validações necessárias;
- riscos ou pontos ainda não definidos.

Não iniciar uma grande implementação sem entender o estado atual.

### IMPLEMENT

Implementar apenas o escopo solicitado.

### TEST

Executar os testes realmente disponíveis e relevantes.

### REVIEW

Revisar:

```bash
git diff

git status
```

### REPORT

Informar:

- o que foi implementado;
- arquivos alterados;
- comandos executados;
- testes executados;
- resultados;
- suposições;
- pontos que requerem hardware;
- pendências.

### STOP

Não iniciar a próxima fase automaticamente.

---

## 12. Regra de leitura do repositório

Antes de criar algo novo, procurar se já existe equivalente.

Evitar:

- classes duplicadas;
- utilitários duplicados;
- schemas redundantes;
- múltiplos clientes HTTP;
- múltiplos formatos Serial;
- múltiplas configurações para a mesma variável.

Preferir extensão ou reutilização de módulos existentes quando coerente.

---

## 13. Não realizar refatoração oportunista

Durante uma tarefa delimitada:

- não reorganizar o projeto inteiro;
- não renomear interfaces públicas sem necessidade;
- não trocar bibliotecas para "melhorar" a solução;
- não migrar frameworks;
- não alterar padrões arquiteturais globais;
- não formatar arquivos não relacionados.

Refatorações amplas exigem uma tarefa própria.

---

## 14. Arquitetura não pode ser alterada silenciosamente

Não substituir sem autorização:

- PostgreSQL por outro banco;
- FastAPI por outro framework;
- React/Vite por outro frontend;
- Arduino Mega 2560 por outro microcontrolador;
- USB/Serial por Wi-Fi;
- contratos REST por arquitetura diferente;
- estratégia de persistência definida no projeto.

Se houver motivo técnico real para mudança:

1. não implementar imediatamente;
2. explicar o problema;
3. apresentar alternativa;
4. aguardar decisão explícita.

---

## 15. Contratos primeiro

Interfaces entre componentes devem ser definidas e respeitadas.

Isso inclui:

- payload Serial;
- schemas Pydantic;
- contratos REST;
- mensagens WebSocket;
- modelos do banco;
- eventos de domínio.

Não modificar um contrato público apenas para facilitar uma implementação local.

Mudanças de contrato devem ser intencionais e propagadas para todos os consumidores.

---

## 16. Protocolo Serial

O formato de comunicação Arduino → host deve ser:

- estruturado;
- versionável;
- testável;
- tolerante a linhas inválidas;
- documentado.

O parser no host deve tratar:

- dados incompletos;
- JSON inválido, se JSON for usado;
- desconexão;
- reconexão;
- mensagens duplicadas;
- campos ausentes;
- valores fora do domínio esperado.

Não alterar o formato Serial silenciosamente após a integração com o host.

---

## 17. Backend

Stack principal:

```text
Python
FastAPI
Pydantic
SQLAlchemy / SQLModel
PostgreSQL
```

Regras:

- usar type hints;
- separar rotas de lógica de negócio;
- preferir services/repositories quando definidos pela arquitetura;
- validar entradas;
- tratar erros explicitamente;
- não retornar stack trace ao cliente;
- não hardcodar segredos;
- usar migrations para mudanças de schema.

---

## 18. Banco de dados

Nunca alterar schema de forma manual como substituto de migration.

Antes de adicionar coluna/tabela:

- procurar modelo existente;
- verificar migration existente;
- verificar impacto em schemas e endpoints;
- verificar índices necessários.

Não apagar dados ou tabelas sem solicitação explícita.

---

## 19. Frontend

Stack principal:

```text
React
TypeScript
Vite
```

Regras:

- evitar `any` sem justificativa;
- manter chamadas à API fora de componentes visuais quando possível;
- reutilizar componentes;
- tratar loading, erro e estado vazio;
- respeitar contratos do backend;
- não duplicar tipos se existir fonte compartilhada ou tipo já definido.

---

## 20. Firmware

Linguagem:

```text
C/C++
```

Regras:

- separar drivers de sensores da lógica de domínio;
- separar comunicação Serial da leitura dos sensores;
- evitar lógica de negócio presa diretamente ao `loop()`;
- preferir funções/classes testáveis;
- não usar `delay()` em lógica crítica se bloquear aquisição ou comunicação;
- usar estados explícitos;
- manter constantes/configurações centralizadas;
- documentar pinos e parâmetros quando forem definidos.

A lógica de detecção deve poder ser testada com valores simulados sempre que possível.

---

## 21. Simulador antes do hardware

Sempre que viável, validar o fluxo de software usando simulador antes da integração física.

O simulador deve poder representar ao menos:

```text
BLUE + sem som
RED + sem som
BLUE + som
RED + som
UNKNOWN
falha de comunicação
mensagem inválida
```

Isso permite testar backend, WebSocket, banco, frontend e alertas antes da Fase 10.

---

## 22. Testes

Não declarar uma tarefa concluída sem executar validações relevantes disponíveis.

Exemplos:

```text
Backend: pytest
Frontend: lint + test + build
Firmware: compile + testes disponíveis
Docker: docker compose config / healthchecks
Serial bridge: testes do parser e integração simulada
```

Se um comando não puder ser executado:

- não fingir que passou;
- registrar o motivo;
- indicar o comando que deverá ser executado posteriormente.

---

## 23. Regra para corrigir testes

Nunca remover uma funcionalidade correta apenas para fazer um teste passar.

Nunca:

- apagar teste válido sem justificativa;
- relaxar assertion para esconder bug;
- substituir erro real por `try/except` genérico;
- ignorar exceção silenciosamente;
- mockar toda a unidade sob teste.

Corrigir a causa do problema.

---

## 24. Dependências

Antes de adicionar dependência:

1. verificar se já existe solução no projeto;
2. justificar necessidade;
3. preferir bibliotecas maduras;
4. manter versão reproduzível;
5. atualizar arquivos de dependência apropriados.

Não instalar pacotes aleatórios para resolver problemas pequenos.

---

## 25. Segurança

Nunca versionar:

- senhas;
- tokens;
- secrets;
- chaves privadas;
- chaves de API;
- credenciais do banco.

Usar variáveis de ambiente e `.env.example` sem valores sensíveis.

Nunca exibir segredos em logs ou respostas.

---

## 26. Git

Antes de alterar:

```bash
git status
```

Depois de alterar:

```bash
git diff

git status
```

Regras:

- preservar mudanças do usuário;
- não sobrescrever arquivos não relacionados;
- não usar comandos destrutivos sem autorização;
- preferir alterações pequenas e coesas;
- não fazer `git reset --hard`;
- não fazer `git clean -fd`;
- não fazer force push.

Commits, quando solicitados, devem ser pequenos e descritivos.

---

## 27. Decisões arquiteturais

Decisões importantes devem ser registradas em:

```text
docs/decisions/
```

Usar ADR quando houver mudança relevante em:

- arquitetura;
- protocolo;
- banco;
- hardware;
- fluxo de eventos;
- segurança;
- estratégia de integração.

Não criar ADR para decisões triviais.

---

## 28. Tratamento de incerteza

Quando houver informação insuficiente, o agente deve preferir uma das seguintes estratégias:

1. procurar no repositório;
2. usar configuração explícita;
3. implementar uma interface sem escolher valor físico;
4. registrar `TODO`;
5. informar a incerteza no relatório.

Não preencher lacunas silenciosamente com valores inventados.

---

## 29. Uso de TODO

`TODO` é aceitável quando a conclusão depende de:

- calibração física;
- hardware ainda não conectado;
- credencial externa;
- decisão do usuário;
- fase futura claramente definida.

Todo TODO deve explicar:

- o que falta;
- por que falta;
- em qual fase deve ser resolvido.

Evitar TODO genérico.

---

## 30. Definição de conclusão

Uma tarefa só pode ser marcada como concluída quando:

- o escopo solicitado foi implementado;
- o código relevante compila/builda quando aplicável;
- os testes disponíveis relevantes foram executados;
- o diff foi revisado;
- nenhum erro conhecido introduzido ficou oculto;
- pendências foram documentadas;
- validações físicas necessárias foram explicitamente separadas.

---

## 31. Formato obrigatório do relatório final

Ao terminar uma tarefa, responder usando esta estrutura:

```text
FASE / TAREFA
<fase e subtarefa executada>

IMPLEMENTADO
- ...

ARQUIVOS ALTERADOS
- ...

VALIDAÇÃO EXECUTADA
- comando: resultado
- comando: resultado

SUPOSIÇÕES
- nenhuma
ou
- ...

REQUER VALIDAÇÃO FÍSICA
- nenhuma
ou
- ...

PENDÊNCIAS
- nenhuma
ou
- ...

PRÓXIMO PASSO RECOMENDADO
- ...
```

Nunca escrever "tudo funcionando" se houver qualquer parte não testada.

---

## 32. Nível de raciocínio recomendado para agentes

Para tarefas simples e bem delimitadas:

```text
Astra 6 — Leve
```

Adequado para:

- CRUD;
- schemas;
- endpoints simples;
- migrations;
- componentes React;
- testes diretos;
- documentação;
- pequenas refatorações locais.

Para tarefas que atravessam múltiplas camadas ou exigem diagnóstico:

```text
Astra 6 — Médio
```

Preferir Médio para:

- arquitetura interna de módulo;
- protocolo Serial;
- máquina de estados;
- concorrência;
- WebSocket;
- autenticação;
- bugs de integração;
- firmware + bridge + API;
- lógica de correlação de eventos;
- debugging difícil.

Após resolver a tarefa complexa, voltar ao nível Leve quando apropriado.

---

## 33. Regra de parada

Ao concluir a tarefa solicitada:

**PARE.**

Não:

- iniciar a próxima fase;
- adicionar funcionalidades "úteis" não solicitadas;
- refatorar módulos vizinhos;
- modificar arquitetura futura;
- preparar integrações que ainda não foram pedidas.

O próximo passo deve ser apenas recomendado, não executado.

---

## 34. Checklist pré-implementação

Antes de editar código, confirmar mentalmente:

```text
[ ] Li AGENTS.md?
[ ] Li a seção correta do PROJECT_MASTER_PROMPT.md?
[ ] Sei exatamente qual fase/tarefa está sendo executada?
[ ] Executei git status?
[ ] Procurei implementação existente?
[ ] Conheço os contratos afetados?
[ ] Há algum valor físico que eu estaria prestes a inventar?
[ ] Sei como validar a mudança?
```

Se alguma resposta for "não", resolver isso antes de continuar.

---

## 35. Checklist pós-implementação

Antes de declarar conclusão:

```text
[ ] O escopo ficou limitado à tarefa?
[ ] Rodei os testes relevantes?
[ ] Rodei build/compile quando aplicável?
[ ] Revisei git diff?
[ ] Revisei git status?
[ ] Listei suposições?
[ ] Separei validação física de validação de software?
[ ] Evitei afirmar algo que não foi testado?
[ ] Não avancei para a próxima fase?
```

---

## 36. Princípio final

O agente deve seguir esta ordem:

```text
EVIDÊNCIA > SUPOSIÇÃO
TESTE > CONFIANÇA
CONTRATO > CONVENIÊNCIA
ESCOPO > AMBIÇÃO
VALIDAÇÃO > VELOCIDADE
```

O objetivo não é produzir o máximo de código possível.

O objetivo é construir o projeto **corretamente, gradualmente e de forma verificável**.
