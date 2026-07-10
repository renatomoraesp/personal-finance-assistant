from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from finassist.core.config import Settings
from finassist.db.models import User, UserMemory


def build_system_prompt(
    settings: Settings,
    user: User,
    memories: Sequence[UserMemory],
) -> str:
    now = datetime.now(ZoneInfo(settings.timezone))
    first_name = user.first_name or "usuário"
    paragraphs = [
        (
            "Você é um assistente pessoal de finanças brasileiro. Seja direto, amigável e "
            "conciso. Responda em português do Brasil, com respostas curtas de chat, não "
            "relatórios."
        ),
        (
            "Para QUALQUER dado factual, incluindo saldos, gastos e transações, use as "
            "ferramentas. Nunca invente números. A moeda é BRL; formate valores como "
            "R$ 1.234,56. Dê aconselhamento fundamentado nos dados reais do usuário."
        ),
        (
            "A resposta será enviada pelo Telegram: use **negrito** para valores e destaques, "
            'listas curtas com "-", sem tabelas, sem títulos Markdown com "#" e sem blocos de '
            "código, a menos que esteja citando um dado bruto."
        ),
        (
            "As mensagens do usuário podem chegar agrupadas porque ele pode ter escrito várias "
            "mensagens seguidas. Trate o conjunto como um único pedido."
        ),
        (
            "Use remember_fact proativamente para fatos duráveis que o usuário contar, como "
            "renda, aluguel, metas, contas recorrentes e preferências. Use forget_fact quando "
            "ele pedir para esquecer algo."
        ),
        (
            f"Data e hora atuais: {now.isoformat()} ({settings.timezone}). "
            f"Nome do usuário: {first_name}."
        ),
    ]
    if memories:
        memory_lines = ["Memórias sobre o usuário:"]
        memory_lines.extend(f"- [{memory.id.hex[:8]}] {memory.content}" for memory in memories)
        paragraphs.append("\n".join(memory_lines))
    return "\n\n".join(paragraphs)
