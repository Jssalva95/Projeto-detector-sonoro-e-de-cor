"""Plain text from persisted occurrence facts; never infer sensor measurements."""

from datetime import timezone

from app.models import Event, Machine


def render_message(event: Event, machine: Machine) -> str:
    color = {'RED': 'VERMELHO', 'BLUE': 'AZUL', 'UNKNOWN': 'DESCONHECIDO'}.get(event.color, 'Não informado')
    sound = 'Não informado' if event.sound_detected is None else 'DETECTADO' if event.sound_detected else 'NÃO DETECTADO'
    amplitude = 'Não informado' if event.sound_amplitude is None else str(event.sound_amplitude)
    timestamp = event.started_at.astimezone(timezone.utc).isoformat()
    return (
        '⚠ ALERTA DE FALHA\n\n'
        f'Máquina: {machine.name}\nNúmero de série: {machine.serial_number}\n'
        f'Local: Bloco {machine.block} — Corredor {machine.corridor}\n\n'
        f'Painel: {color}\nAlarme sonoro: {sound}\n'
        f'Nível sonoro relativo: {amplitude}\n\n'
        f'Horário: {timestamp}\nOcorrência: {event.uuid}\n\n'
        'Favor verificar o equipamento imediatamente.'
    )
