"""Lance l'API et l'interface : python -m agent_tag.api [--hote 127.0.0.1] [--port 8000].

L'API n'a PAS d'authentification : l'identité est un simple sélecteur (en-tête X-Utilisateur).
Elle n'écoute donc que sur la boucle locale ; toute autre adresse est refusée.
"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from agent_tag.api.app import creer_app

HOTES_LOCAUX = {"127.0.0.1", "localhost", "::1"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agent_tag.api")
    p.add_argument("--hote", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--fichier-pid", type=Path, default=None,
                   help="écrit le numéro de ce processus dans ce fichier (scripts d'arrêt)")
    args = p.parse_args(argv)
    if args.hote not in HOTES_LOCAUX:
        print(f"refusé : --hote {args.hote}. Sans authentification, l'application ne doit être "
              "accessible que depuis ce poste (127.0.0.1).", file=sys.stderr)
        return 2
    app = creer_app()
    if args.fichier_pid:
        args.fichier_pid.write_text(str(os.getpid()), encoding="ascii")
    try:
        uvicorn.run(app, host=args.hote, port=args.port)
    finally:
        if args.fichier_pid:
            args.fichier_pid.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
