from discord import app_commands


def admin_only():
    """Slash command check: 只允許伺服器管理員或機器人管理員使用。"""
    async def predicate(interaction) -> bool:
        if not interaction.guild:
            return False
        return interaction.client.db.is_admin(interaction.guild_id, interaction.user)
    return app_commands.check(predicate)
