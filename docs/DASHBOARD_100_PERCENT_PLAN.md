# Plano para deixar o Web Dashboard 100% funcional

Branch de trabalho: `feat/dashboard-phase2-safe`

Este plano existe para transformar o painel web em uma interface real de administracao do bot, sem ser apenas visual. A regra principal e: qualquer configuracao vista no Discord via `/config` deve ser lida da mesma fonte do bot e qualquer mudanca feita no painel web deve atualizar a mesma configuracao usada pelo bot no Discord.

## Principios obrigatorios

1. Nao duplicar configuracao.
   - O painel web nao deve ter uma tabela separada ou valores proprios para fingir que configurou algo.
   - Deve ler e salvar nos mesmos models/services/repositories usados pelo bot.

2. Nao quebrar o `/config`.
   - O Discord continua sendo uma interface valida.
   - O painel web vira outra interface em cima da mesma base.

3. Nao mexer direto na `master`.
   - Toda mudanca continua na branch `feat/dashboard-phase2-safe`.
   - Merge so depois de testes locais.

4. Configuracao sem efeito e proibida.
   - Cada campo precisa ter origem clara: model, attr, service updater e efeito no bot.
   - Campo que ainda nao tiver backend funcional deve aparecer como pendente/desativado ou nao aparecer.

5. Atualizacao em duas vias.
   - Se mudou no Discord, o painel precisa perceber.
   - Se mudou no painel, o bot precisa usar o novo valor sem reiniciar quando possivel.

## Estado atual da branch

Ja foi criada a fundacao segura das configuracoes:

- keys namespaced, evitando colisao entre `enabled`, `channel_id`, `log_channel_id`, `verified_role_id` e outros campos repetidos.
- router novo de settings separado do legado.
- unidades para campos de tempo.
- sidebar com mais secoes.
- teste estatico inicial passando.

## Fase 1 - Fonte unica de configuracao

Objetivo: garantir que dashboard e `/config` sempre falam com a mesma fonte.

Tarefas:

- Mapear todas as categorias retornadas por `iter_categories(bot)` em `views/master_config_view.py`.
- Para cada categoria, registrar:
  - nome da secao;
  - model usado;
  - campos expostos;
  - updater/service chamado;
  - se a mudanca exige refresh de mensagem, cache ou painel do Discord.
- Criar um endpoint de diagnostico local para listar o mapa de configs:
  - key namespaced;
  - model;
  - attr;
  - tipo;
  - unidade;
  - se e editavel;
  - se possui updater.
- Adicionar teste garantindo que toda key exposta pelo dashboard tem updater valido.

Criterio de pronto:

- Nenhum campo aparece no painel sem ter caminho real de leitura/salvamento.
- Toda configuracao do dashboard tambem reflete a base usada pelo `/config`.

## Fase 2 - Sincronizacao painel web <-> Discord

Objetivo: evitar F5 manual e evitar painel desatualizado.

Tarefas:

- Implementar canal de eventos local para o dashboard, preferencialmente SSE.
- Quando o bot alterar configuracao pelo `/config`, emitir evento `settings.changed`.
- Quando o painel alterar configuracao, emitir evento `settings.changed` e invalidar caches do frontend.
- Eventos minimos:
  - `settings.changed`;
  - `ticket.changed`;
  - `staff.changed`;
  - `panel.changed`;
  - `giveaway.changed`;
  - `dlc.changed`;
  - `audit.changed`;
  - `guild.changed`.
- Frontend deve invalidar queries especificas, nao recarregar a tela toda.
- Fallback: polling moderado onde SSE nao estiver disponivel.

Criterio de pronto:

- Alterar uma config no `/config` aparece no painel sem precisar F5.
- Alterar uma config no painel afeta o bot e aparece no `/config`.

## Fase 3 - Validacao forte de configs

Objetivo: impedir erro inesperado e config invalida.

Tarefas:

- Validar se canais existem na guild antes de salvar.
- Validar se cargos existem na guild antes de salvar.
- Validar se o bot tem permissao no canal/cargo quando isso for necessario.
- Validar valores numericos com min/max.
- Validar campos de tempo com unidade clara.
- Bloquear combinacoes perigosas, exemplo:
  - auto-close ativado com tempo zero;
  - ranking sem canal quando auto-publicacao estiver ativa;
  - avaliacao DM sem mensagem/titulo padrao valido;
  - verificacao sem cargo verificado quando ela exigir cargo.
- Exibir erro claro no frontend, sem travar a pagina.

Criterio de pronto:

- Config errada nao salva silenciosamente.
- O usuario entende o que precisa corrigir.

## Fase 4 - Paginas reais, nao decorativas

Objetivo: cada pagina do dashboard deve executar a acao real do bot.

Prioridade de paginas:

1. Configuracoes gerais do bot.
2. Tickets e paineis.
3. Verificacao.
4. Avaliacoes.
5. Ranking/staff.
6. Sorteios.
7. DLCs.
8. Monetizacao/planos/cupons/pagamentos.
9. Moderacao/punicoes/recursos.
10. Auditoria/export/import/reset.

Regra:

- Se a pagina so mostra informacao e nao consegue executar a acao real, marcar como leitura ou pendente.
- Nao criar botao de enfeite.

## Fase 5 - Sorteios no painel web

Objetivo: criar, listar, encerrar, cancelar e rerollar sorteios pelo dashboard usando o mesmo backend do bot.

Tarefas:

- Usar `GiveawayService`.
- Adicionar metodo de cancelamento no service se ainda nao existir.
- Rotas admin:
  - listar sorteios;
  - criar/publicar sorteio;
  - encerrar;
  - cancelar;
  - reroll;
  - listar participantes/vencedores quando seguro.
- Frontend:
  - pagina `/giveaways`;
  - formulario com canal, titulo, descricao, duracao, quantidade de vencedores, cargo permitido, premio em cargo ou texto.
- Validar permissao do bot no canal.

Criterio de pronto:

- Sorteio criado no painel aparece no Discord com embed/botao real.
- Sorteio encerrado/cancelado no painel atualiza o Discord.

## Fase 6 - DLCs no painel web

Objetivo: criar e administrar DLC gratuita/paga pelo dashboard usando `DlcService`.

Regras atuais do projeto:

- DLC gratuita usa cargo verificado configurado na guild.
- DLC paga usa cargo exclusivo + plano/produto.
- Nao mexer em launcher/R2/itch agora.
- DLC continua baked no jogo.

Tarefas:

- Rotas admin:
  - listar DLCs;
  - criar DLC gratuita;
  - criar DLC paga;
  - editar nome/descricao;
  - editar preco da paga;
  - editar cargo da paga;
  - ativar/desativar;
  - soft delete.
- Frontend:
  - pagina `/dlcs`;
  - formulario separado para gratuita/paga;
  - mostrar status, preco, cargo, slug e plano vinculado.
- Validar slug unico e cargo existente.

Criterio de pronto:

- Criar DLC no painel gera o mesmo resultado de criar pelo fluxo do bot.
- DLC gratuita nao pede cargo manual se o sistema ja usa `verified_role_id`.

## Fase 7 - Robustez contra travamento

Objetivo: painel nao travar o bot e bot nao travar o painel.

Tarefas:

- Evitar consultas pesadas em loop curto.
- Evitar `asyncio.gather` sem limite em operacoes grandes.
- Colocar timeout e tratamento de erro em operacoes Discord API.
- Padronizar respostas de erro da API.
- Frontend deve ter loading, empty state e error state em toda pagina.
- Nao bloquear o event loop do Discord com operacoes pesadas do dashboard.

Criterio de pronto:

- Uma falha no Discord API nao derruba o dashboard.
- Uma falha do dashboard nao derruba o bot.

## Fase 8 - Auditoria e seguranca local

Objetivo: toda acao importante ficar registrada e protegida.

Tarefas:

- Toda mudanca do painel registra audit log.
- Audit log deve indicar origem: `dashboard`.
- Validar guild em todas as rotas.
- Manter `require_local_admin`.
- Adicionar rate limit local basico em acoes destrutivas.
- Nunca expor token, secrets, env ou dados sensiveis no frontend.

Criterio de pronto:

- Da para descobrir quem/qual origem alterou configuracao.
- Acoes perigosas nao ficam abertas sem validacao.

## Fase 9 - Testes obrigatorios

Backend:

- settings keys unicas;
- patch altera somente a key namespaced correta;
- `/config` e dashboard leem a mesma origem;
- validacao de canal/cargo inexistente;
- sorteios usando service;
- DLCs usando service;
- eventos SSE emitidos.

Frontend:

- build TypeScript;
- paginas carregam sem dados;
- paginas mostram erro sem crash;
- forms salvam e invalidam cache;
- DurationInput preserva unidade canonica.

Manual:

- mudar config no Discord e ver no painel;
- mudar config no painel e conferir no Discord;
- criar sorteio no painel;
- criar DLC gratuita no painel;
- criar DLC paga no painel;
- reiniciar bot e conferir se nada reseta.

## Ordem segura de execucao

1. Finalizar Fase 1 e 3 das configs.
2. Implementar SSE da Fase 2.
3. Melhorar sidebar e UX das secoes existentes.
4. Implementar Sorteios.
5. Implementar DLCs.
6. Implementar Monetizacao.
7. Implementar Moderacao/recursos.
8. Rodar testes completos.
9. Abrir PR para revisar antes de merge.

## O que nao fazer

- Nao criar configuracao duplicada so para o painel.
- Nao criar botao que nao chama service real.
- Nao salvar `enabled` sem namespace.
- Nao misturar `avaliacoes.enabled` com `verificacao.enabled`.
- Nao alterar `master` direto.
- Nao apagar mudancas locais existentes sem revisao.
