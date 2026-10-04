# Códigos de resgate

O painel de Monetização permite configurar uma recompensa por código: uma mensagem privada ou um cargo acompanhado de mensagem. Os códigos têm exatamente oito caracteres ASCII, incluem letras e números e são comparados em maiúsculas. Cada pessoa pode resgatar cada código uma vez. O limite total, o período de validade e a duração do cargo são independentes.

## Privacidade

O botão da loja abre um formulário privado. A mensagem de sucesso aparece como resposta efêmera no canal da loja ou por DM, conforme a configuração. Se a DM estiver bloqueada, a interação permite um retorno privado. Não se publica o código digitado no canal.

## Cargos temporários

Cargos usados na loja, em planos ou em outros recursos também podem ser recompensas. Se um cargo temporário estiver compartilhado quando vencer, a remoção automática será suspensa e o cargo será preservado, com o motivo no histórico. Use um cargo dedicado quando precisar de remoção automática ao vencer. Cargos com permissões administrativas continuam proibidos. O Discord não informa a origem de um cargo; uma concessão manual posterior pode ser indistinguível de uma concessão existente.

O bot precisa de Gerenciar Cargos e de um cargo acima da recompensa. Para cargos temporários, também precisa de Ver Registro de Auditoria. A configuração exige confirmar que a expiração respeita outras configurações e atribuições manuais.

A rotina de expiração preserva concessões ainda válidas e suspende remoções quando encontra conflito com outra configuração. Antes de remover, procura a concessão original do bot e alterações externas no registro de auditoria. A proteção existente de cargos de assinaturas permanece independente.

A conferência de auditoria é limitada aos registros recentes. Uma concessão antiga, alterações suficientes para ultrapassar a janela consultada ou falta de permissão podem suspender a remoção para revisão. Não atribua manualmente um cargo dedicado enquanto houver concessões temporárias ativas.

O processamento ocorre periodicamente. Uma indisponibilidade do bot, do banco ou do Discord pode atrasar a entrega ou a remoção. O vencimento do código é verificado no momento de reservar o resgate; uma reserva aceita antes do vencimento pode terminar depois dele.

## Falhas e histórico

As reservas pendentes contam para o limite total. Uma falha definitiva antes da entrega libera a reserva; um resultado incerto precisa de verificação antes de liberar o uso. Reiniciar o bot não apaga reservas, concessões nem histórico.

O banco e o Discord não compartilham uma transação. Por isso, um envio de mensagem com resposta perdida pode permanecer incerto. Não prometa entrega de mensagens exatamente uma vez. A falha da mensagem não desfaz um cargo já concedido.

DMs concluídas com notificação ainda não iniciada são recuperadas após reinício. Se o Discord recusar definitivamente a DM, a mensagem fica disponível ao consultar o mesmo código na loja. Mensagens efêmeras dependem da interação: se a entrega do cargo concluir depois, consulte novamente o mesmo código para obter o resultado privado, sem novo uso. Envios incertos não são repetidos automaticamente.

## Validação e ativação

Execute os testes com Discord simulado. Os testes de concorrência usam exclusivamente um PostgreSQL local descartável, identificado por `TEST_REDEMPTION_DATABASE_URL`. O nome do banco deve começar com `redemption_test`; hosts externos são rejeitados. Cada teste cria e remove somente seu próprio esquema aleatório. Nunca use a URL do banco de produção nesses testes.

Defina `PYTHON_DOTENV_DISABLED=1` no processo de testes para impedir o carregamento de credenciais do `.env`. Os testes novos estão em `tests/test_redemption_*.py`. A migração é `b8e4c2d6f019_redemption_codes.py`, posterior à proteção de canais existente.

Antes de ativar em produção, faça backup e aplique a migração aditiva pelo procedimento habitual do projeto. Depois, valide em um servidor de testes: código de mensagem, código de cargo permanente, código de cargo temporário, DM bloqueada e limite de usos. Reinicie o bot para confirmar que o botão persistente e as pendências sobrevivem.

Desativar um código impede novas reservas, sem apagar o histórico ou desfazer as recompensas já entregues. Parar o bot também interrompe temporariamente a rotina de expiração.
