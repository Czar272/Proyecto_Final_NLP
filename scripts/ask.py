"""CLI: realiza una consulta al asistente y muestra la respuesta JSON validada.

Ejemplo:
    python scripts/ask.py "¿Cuántos días de vacaciones me corresponden?" --user EMP-001 --role empleado
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hrrag.agent.orchestrator import HRAssistant  # noqa: E402
from hrrag.schemas import Role, UserContext  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--user", default="EMP-001")
    parser.add_argument("--role", default="empleado", choices=[r.value for r in Role])
    parser.add_argument("--confirm", action="store_true", help="Confirma explícitamente una acción crítica")
    parser.add_argument("--trace", action="store_true", help="Muestra la traza de auditoría completa")
    args = parser.parse_args()

    assistant = HRAssistant()
    resp, trace = assistant.ask(args.question, UserContext(user_id=args.user, role=Role(args.role)),
                                confirm_action=args.confirm)
    print(json.dumps(resp.model_dump(), indent=2, ensure_ascii=False))
    if args.trace:
        print(json.dumps(trace, indent=2, ensure_ascii=False, default=str))
