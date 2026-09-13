"""Démarre le menu et affiche les erreurs sans fermer immédiatement la fenêtre."""

from pathlib import Path
import sys


def main() -> int:
    """Enregistre les médias à côté de l'exe, ou de ce script en développement."""
    try:
        # Import différé pour afficher clairement une dépendance Python manquante.
        from downloader.cli import run

        location = sys.executable if getattr(sys, "frozen", False) else __file__
        return run(Path(location).resolve().parent)
    except ImportError as error:
        print(f"Bibliothèque Python manquante ou inutilisable : {error}")
        print("Depuis les sources : python -m pip install -r requirements.txt")
        print("Pour l'exe : recompilez après avoir installé les dépendances.")
    except Exception as error:
        print(f"Impossible de démarrer : {error}")
    try:
        # Après un double-clic, laisse le diagnostic visible avant de fermer.
        input("Appuyez sur Entrée pour fermer.")
    except (EOFError, KeyboardInterrupt):
        pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
