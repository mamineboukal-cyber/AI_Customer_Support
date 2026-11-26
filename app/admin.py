"""Admin command line.

    python -m app.admin list                  waiting inquiries
    python -m app.admin answer ID "text"      answer ledger question ID for everyone waiting

Exit code: 0 ok, 1 some replies were not delivered, 2 bad request (nothing written).
"""
import argparse
import sys

from app.rag.admin_answers import AdminAnswerError, answer_inquiry, list_waiting


def _list():
    rows = list_waiting()
    if not rows:
        print("No waiting inquiries.")
        return 0
    print(f"{'inquiry':>7}  {'ledger':>6}  {'freq':>4}  {'conv':>6}  {'raised':<16}  topic")
    for r in rows:
        print(
            f"{r.inquiry_id:>7}  {r.ledger_id:>6}  {r.frequency:>4}  {r.conversation_id:>6}  "
            f"{r.created_at:%Y-%m-%d %H:%M}  {r.topic}"
        )
    return 0


def _answer(ledger_id, text):
    try:
        results = answer_inquiry(ledger_id, text)
    except AdminAnswerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for r in results:
        print(f"[{r.status}] inquiry {r.inquiry_id}, conversation {r.conversation_id}")
        print(f"    {r.reply if r.reply is not None else r.error}")
    delivered = sum(r.status == "delivered" for r in results)
    print(f"{delivered}/{len(results)} delivered")
    return 0 if delivered == len(results) else 1


def main(argv=None):
    # Arabic and French replies must print on a Windows console too
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the waiting inquiries")
    answer = commands.add_parser("answer", help="answer one ledger question")
    answer.add_argument("ledger_id", type=int)
    answer.add_argument("text", help="the admin's answer")
    args = parser.parse_args(argv)
    if args.command == "list":
        return _list()
    return _answer(args.ledger_id, args.text)


if __name__ == "__main__":
    sys.exit(main())
