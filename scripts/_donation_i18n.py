"""Store texts of the one-time donation product, one entry per store listing language.

The purchase sheet of each store shows this title, so every listing language has its own
text (never the en-US fallback). Keys are App Store locales; PLAY maps them to Play's codes.
ASC caps the name at 35 characters and the description at 55.
"""
from __future__ import annotations

ENGLISH = ("Support development", "A one-time thank-you. Nothing in the app changes.")

TEXT = {
    "en-US": ENGLISH,
    "en-GB": ENGLISH,
    "en-AU": ENGLISH,
    "en-CA": ENGLISH,
    "ca": ("Dona suport al desenvolupament", "Un agraïment puntual. L'aplicació no canvia."),
    "da": ("Støt udviklingen", "En engangstak. Intet i appen ændres."),
    "es-ES": ("Apoyar el desarrollo", "Un agradecimiento único. La aplicación no cambia."),
    "es-MX": ("Apoyar el desarrollo", "Un agradecimiento único. La aplicación no cambia."),
    "fr-FR": ("Soutenir le développement", "Un merci ponctuel. Rien ne change dans l'application."),
    "fr-CA": ("Soutenir le développement", "Un merci ponctuel. Rien ne change dans l'application."),
    "hr": ("Podrži razvoj", "Jednokratna zahvala. U aplikaciji se ništa ne mijenja."),
    "it": ("Sostieni lo sviluppo", "Un grazie una tantum. Nell'app non cambia nulla."),
    "no": ("Støtt utviklingen", "En engangstakk. Ingenting i appen endres."),
    "pt-BR": ("Apoiar o desenvolvimento", "Um agradecimento único. Nada muda no app."),
    "pt-PT": ("Apoiar o desenvolvimento", "Um agradecimento único. Nada muda na aplicação."),
    "ro": ("Susține dezvoltarea", "O mulțumire unică. Nimic nu se schimbă în aplicație."),
    "ru": ("Поддержать разработку", "Разовая благодарность. В приложении ничего не меняется."),
    "sv": ("Stöd utvecklingen", "Ett engångstack. Inget i appen ändras."),
    "uk": ("Підтримати розробку", "Разова подяка. У додатку нічого не змінюється."),
}

PLAY = {
    "en-US": "en-US", "en-GB": "en-GB", "en-AU": "en-AU", "en-CA": "en-CA",
    "ca": "ca", "da": "da-DK", "es-ES": "es-ES", "es-MX": "es-419",
    "fr-FR": "fr-FR", "fr-CA": "fr-CA", "hr": "hr", "it": "it-IT", "no": "no-NO",
    "pt-BR": "pt-BR", "pt-PT": "pt-PT", "ro": "ro", "ru": "ru-RU", "sv": "sv-SE", "uk": "uk",
}

for _locale, (_name, _description) in TEXT.items():
    if len(_name) > 35 or len(_description) > 55:
        raise SystemExit(f"{_locale}: over ASC's 35/55 caps: {_name!r} / {_description!r}")
    if not _locale.startswith("en") and (_name, _description) == ENGLISH:
        raise SystemExit(f"{_locale}: English text in a non-English locale")
