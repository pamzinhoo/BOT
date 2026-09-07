# Next implementation prompt

Use this after Phase A has been tested locally.

```text
Voce esta no repo pamzinhoo/BOT, branch feat/dashboard-phase2-safe.

Objetivo: implementar a Phase B do Web Dashboard sem quebrar o bot Discord.

Contexto:
- A Phase A ja corrigiu a fundacao de settings com chaves namespaced.
- Nao refaca essa base.
- Nao mexa em distribuicao do jogo, itch.io, launcher ou R2.

Escopo da Phase B:
1. Criar pagina web para Sorteios usando os servicos existentes:
   - listar sorteios ativos/encerrados/cancelados
   - ver participantes/quantidade
   - criar sorteio
   - encerrar/finalizar
   - sortear novamente quando encerrado
   - cancelar somente se houver suporte seguro no service; se nao houver, implemente no service antes da rota
2. Criar pagina web para DLCs usando DlcService existente:
   - listar DLCs
   - criar DLC gratuita usando cargo Verificado automaticamente
   - criar DLC paga com preco e cargo escolhido
   - editar nome/descricao
   - editar preco somente de DLC paga
   - editar cargo somente de DLC paga
   - ativar/desativar
   - soft-delete
3. Todas as rotas novas devem chamar services existentes, nao SQL direto.
4. Toda acao mutavel deve registrar audit log.
5. Validar guild_id, canal, cargo, valores numericos, preco em centavos, status e UUID.
6. Manter dashboard local-only atual; nao implementar auth remota ainda.
7. Adicionar testes focados de API/service para acoes criticas.
8. Rodar testes relevantes e build do frontend.

Nao faca:
- Nao mexa na master.
- Nao faca push sem revisar diff.
- Nao altere fluxo de pagamento existente fora do necessario para DLC.
- Nao crie migracao se nao for indispensavel.

Entrega:
- Resumo tecnico
- Arquivos alterados
- Testes rodados
- Riscos restantes
- Checklist manual
```
