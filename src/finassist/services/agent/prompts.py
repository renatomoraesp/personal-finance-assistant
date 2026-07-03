from datetime import datetime
from zoneinfo import ZoneInfo

from finassist.core.config import Settings
from finassist.db.models import User


def build_system_prompt(settings: Settings, user: User) -> str:
    now = datetime.now(ZoneInfo(settings.timezone))
    first_name = user.first_name or "usuário"
    return (
        "Você é um assistente brasileiro de finanças pessoais, afiado, amigável e conciso. "
        "Responda em português do Brasil por padrão. Use as ferramentas para qualquer pergunta "
        "sobre dados financeiros factuais do usuário; nunca chute, nunca invente transações. "
        "A moeda é BRL; formate valores como R$ 1.234,56. Ao dar conselhos, fundamente-os nos "
        "dados reais disponíveis. "
        f"Data e hora atuais: {now.isoformat()} ({settings.timezone}). "
        f"Nome do usuário: {first_name}."
    )
