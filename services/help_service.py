from __future__ import annotations

from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.command_help import CommandHelp
from database.repositories.command_help_repository import CommandHelpRepository
from services.audit_log_service import AuditLogService

_PERMISSION_RANK = {"public": 0, "staff": 1, "admin": 2}


class HelpService:
    """Fonte dos dados do /help — comandos ficam cadastrados em `command_help` e
    sao filtrados por permissao aqui, sem precisar tocar no cog/views quando um
    comando novo e cadastrado (Etapa 10)."""

    def __init__(self, database: Database, audit_log_service: AuditLogService) -> None:
        self._database = database
        self._audit_log_service = audit_log_service

    @staticmethod
    def _member_rank(*, is_admin: bool, is_staff: bool) -> int:
        if is_admin:
            return _PERMISSION_RANK["admin"]
        if is_staff:
            return _PERMISSION_RANK["staff"]
        return _PERMISSION_RANK["public"]

    async def list_visible_by_category(
        self, category: str, *, is_admin: bool, is_staff: bool
    ) -> list[CommandHelp]:
        rank = self._member_rank(is_admin=is_admin, is_staff=is_staff)
        async with self._database.session() as session:
            commands = await CommandHelpRepository(session).list_by_category(category)
        return [c for c in commands if _PERMISSION_RANK.get(c.required_permission, 0) <= rank]

    async def list_all_visible(self, *, is_admin: bool, is_staff: bool) -> list[CommandHelp]:
        rank = self._member_rank(is_admin=is_admin, is_staff=is_staff)
        async with self._database.session() as session:
            commands = await CommandHelpRepository(session).list_enabled()
        return [c for c in commands if _PERMISSION_RANK.get(c.required_permission, 0) <= rank]

    async def get_visible_command(
        self, command_name: str, *, is_admin: bool, is_staff: bool
    ) -> CommandHelp | None:
        rank = self._member_rank(is_admin=is_admin, is_staff=is_staff)
        async with self._database.session() as session:
            command = await CommandHelpRepository(session).get_by_command_name(command_name)
        if command is None or not command.enabled:
            return None
        if _PERMISSION_RANK.get(command.required_permission, 0) > rank:
            return None
        return command

    async def register_command(
        self,
        *,
        guild_id: int,
        actor_id: int,
        actor_name: str,
        command_name: str,
        category: str,
        description: str,
        usage: str,
        examples: list[str],
        required_permission: str = "public",
    ) -> CommandHelp:
        """Cria ou atualiza (upsert por command_name) um comando na central de ajuda."""
        async with self._database.session() as session:
            repo = CommandHelpRepository(session)
            command = await repo.get_by_command_name(command_name)
            if command is None:
                command = await repo.add(
                    CommandHelp(
                        command_name=command_name,
                        category=category,
                        description=description,
                        usage=usage,
                        examples=examples,
                        required_permission=required_permission,
                    )
                )
            else:
                command.category = category
                command.description = description
                command.usage = usage
                command.examples = examples
                command.required_permission = required_permission
                command.enabled = True
            await session.flush()
            await session.refresh(command)

        await self._audit_log_service.record(
            guild_id=guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="HELP_COMMAND_CREATED",
            executor_id=actor_id,
            executor_name=actor_name,
            target_name=command_name,
        )
        return command

    async def remove_command(
        self, *, guild_id: int, actor_id: int, actor_name: str, command_name: str
    ) -> bool:
        async with self._database.session() as session:
            repo = CommandHelpRepository(session)
            command = await repo.get_by_command_name(command_name)
            if command is None:
                return False
            command.enabled = False
            await session.flush()

        await self._audit_log_service.record(
            guild_id=guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="HELP_COMMAND_REMOVED",
            executor_id=actor_id,
            executor_name=actor_name,
            target_name=command_name,
        )
        return True
