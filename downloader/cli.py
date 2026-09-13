"""Interface terminal française et validation des saisies."""

from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp.utils import DownloadError

from .formats import Choice, choices_for
from .service import base_options, download, inspect_url


def ask_choice(choices: list[Choice]) -> Choice | None:
    """Attend un numéro valide ; zéro revient à la saisie d'URL."""
    for index, choice in enumerate(choices, 1):
        print(f"  {index:2}. {choice.label}")
    print("   0. Annuler")
    while True:
        value = input("Votre choix : ").strip()
        if value.isdecimal():
            number = int(value)
            if 0 <= number <= len(choices):
                return choices[number - 1] if number else None
        print(f"Entrez un numéro entre 0 et {len(choices)}.")


def ask_again() -> bool:
    """Attend une réponse explicite avant un nouveau téléchargement."""
    while True:
        answer = input("\nFaire un autre téléchargement ? [o/n] : ").strip().lower()
        if answer in {"n", "non"}:
            return False
        if answer in {"o", "oui"}:
            return True
        print("Répondez par o ou n.")


def run(output: Path) -> int:
    """Enchaîne les téléchargements jusqu'à quitter ou fermer l'entrée."""
    print("\n=== Media Downloader — vidéo / audio ===")
    print(f"Destination : {output}\n")
    options = base_options(output)
    try:
        while True:
            url = input("URL du média (q pour quitter) : ").strip()
            if url.lower() in {"q", "quitter", "exit"}:
                return 0
            try:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError(
                        "Entrez une URL complète commençant par https:// ou http://."
                    )
                print("Analyse du lien et des formats disponibles…")
                info = inspect_url(url, options)
                print(f"\n{info.get('title', 'Média sans titre')}")
                choices = choices_for(info)
                if not choices:
                    raise ValueError(
                        "Aucun format téléchargeable disponible pour ce média."
                    )
                choice = ask_choice(choices)
                if choice is None:
                    continue
                print("\nTéléchargement en cours…")
                download(url, choice, options)
                print(f"\nTerminé. Fichier disponible dans : {output}")
            except (DownloadError, ValueError, OSError, RuntimeError) as error:
                print(f"\nImpossible de terminer : {error}")
                print(
                    "Vérifiez le lien, la connexion, l'espace disque et les droits d'accès."
                )
            if not ask_again():
                return 0
    except (KeyboardInterrupt, EOFError):
        print(
            "\nArrêt demandé. Les fichiers partiels permettent une reprise ultérieure."
        )
        return 0
