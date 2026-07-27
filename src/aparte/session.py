from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import RecordingError


class ToggleSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordingSession:
    pid: int
    audio_path: Path
    sample_rate: int
    started_at: float


# Vrai parce que `start_toggle_recording` impose `-f S16_LE -c 1` : en-tête RIFF,
# `fmt ` de 16 octets, puis `data`. Ne pas réutiliser comme vérité WAV générale.
_ARECORD_WAV_HEADER_BYTES = 44

# En dessous, il n'y a pas de dictée : ce sont les miettes d'un démarrage raté.
# Whisper fabrique du texte sur trois millisecondes de bruit comme sur du silence.
MIN_TRANSCRIBABLE_SECONDS = 0.3

# Le délai qu'on laisse à `arecord` pour prouver qu'il capte vraiment. Mesuré sur
# un micro USB : `Popen` rend la main dès l'exec (0,001 s), le fichier apparaît à
# 0,04 s et le premier échantillon à 0,17 s — mais un `-D plughw:` déjà tenu par
# une autre application ne fait sortir arecord qu'à 0,02-0,05 s. Décider avant,
# c'est annoncer une dictée à un enregistreur déjà condamné.
_START_CONFIRMATION_SECONDS = 0.75
_START_POLL_SECONDS = 0.02

# En dessous, un enregistreur n'est pas encore un oubli : un appui concurrent peut
# être en train de publier sa session. Au-delà, plus personne ne viendra le faire.
_ORPHAN_GRACE_SECONDS = 2.0
# Ce qu'on laisse à un enregistreur ramassé pour rendre le micro.
_ORPHAN_EXIT_SECONDS = 1.0


def get_runtime_dir() -> Path:
    override = os.getenv("APARTE_RUNTIME_DIR")
    if override:
        candidates = [Path(override).expanduser()]
    else:
        candidates = []
        if os.getenv("XDG_RUNTIME_DIR"):
            candidates.append(Path(os.environ["XDG_RUNTIME_DIR"]) / "aparte")
        candidates.append(Path(tempfile.gettempdir()) / f"aparte-{os.getuid()}")
    last_error: OSError | None = None
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except OSError as exc:
            last_error = exc
    raise ToggleSessionError(f"No writable runtime directory found: {last_error}")


def get_session_path() -> Path:
    return get_runtime_dir() / "toggle-session.json"


def _captured_seconds(session: RecordingSession) -> float:
    """Combien de son ce fichier porte vraiment.

    Calculé sur la taille, jamais sur l'en-tête : sans durée imposée, `arecord`
    plafonne le WAV à 2 Gio et écrit un en-tête bouche-trou de 0x40000000
    trames, qu'il ne corrige qu'en sortant proprement. Tué avant, il annonce
    67 108 s pour trois secondes de son — n'importe quel seuil de durée lu là
    laisserait passer les miettes qu'il doit justement rejeter.
    """
    try:
        payload = session.audio_path.stat().st_size - _ARECORD_WAV_HEADER_BYTES
    except OSError:
        return 0.0
    # S16_LE mono : deux octets par échantillon.
    return max(0.0, payload / (session.sample_rate * 2))


def _recorder_alive(session: RecordingSession) -> bool:
    """Ce PID est-il toujours *notre* arecord, et pas un PID recyclé ?

    Le noyau réattribue les PID libérés : `os.kill(pid, 0)` répondrait vrai pour
    le processus de quelqu'un d'autre, et `killpg` enverrait alors un SIGINT à
    tout son groupe. Le chemin du fichier est unique par session, donc il
    distingue même deux arecord lancés en même temps.
    """
    try:
        cmdline = Path(f"/proc/{session.pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"arecord" in cmdline and os.fsencode(session.audio_path) in cmdline


def get_active_session() -> RecordingSession | None:
    path = get_session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = RecordingSession(
            pid=int(data["pid"]),
            audio_path=Path(str(data["audio_path"])),
            sample_rate=int(data["sample_rate"]),
            started_at=float(data["started_at"]),
        )
    except Exception:
        # L'écriture passe par `_claim_session`, donc un fichier illisible n'est
        # plus un état transitoire : c'est de la corruption. Le supprimer est la
        # récupération — le garder bloquerait toute dictée future.
        path.unlink(missing_ok=True)
        return None
    if _recorder_alive(session):
        return session
    # L'enregistreur a fini seul : plafond atteint, ou refus au démarrage. Ce
    # qu'il a capté reste une dictée à transcrire au prochain appui. La
    # supprimer ici détruirait l'enregistrement à la seconde même où
    # l'utilisateur appuie pour le récupérer.
    if _captured_seconds(session) >= MIN_TRANSCRIBABLE_SECONDS:
        return session
    path.unlink(missing_ok=True)
    session.audio_path.unlink(missing_ok=True)
    return None


def _claim_session(session: RecordingSession) -> bool:
    """Prendre la session pour nous. False si un autre appui l'a déjà prise.

    Le lien physique est atomique et exclusif : ou bien il publie le fichier
    complet d'un seul coup, ou bien il échoue parce que la cible existe. Un
    lecteur ne voit donc jamais de JSON tronqué — ce qui, avant, le faisait
    supprimer la session d'un enregistrement bien vivant.
    """
    path = get_session_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "pid": session.pid,
                "audio_path": str(session.audio_path),
                "sample_rate": session.sample_rate,
                "started_at": session.started_at,
            }
        ),
        encoding="utf-8",
    )
    try:
        os.link(temporary, path)
        return True
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)


def _clear_stale_temporaries() -> None:
    """Ramasser les temporaires d'un processus tué entre l'écriture et le lien.

    Seulement les vieux : un temporaire tout frais appartient peut-être encore à
    un appui concurrent en train de publier sa session.
    """
    path = get_session_path()
    cutoff = time.time() - 60
    for leftover in path.parent.glob(f"{path.name}.*.tmp"):
        try:
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink(missing_ok=True)
        except OSError:
            continue


def _stop_recorder(session: RecordingSession, number: int = signal.SIGINT) -> None:
    """Arrêter l'enregistreur de cette session, s'il est encore le nôtre."""
    if not _recorder_alive(session):
        return
    try:
        os.killpg(session.pid, number)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise ToggleSessionError(f"Cannot stop recording process {session.pid}: {exc}") from exc


def _capture_confirmed(session: RecordingSession) -> bool:
    """Attendre qu'`arecord` prouve qu'il capte, ou qu'il meure sans avoir capté.

    Le premier échantillon écrit est la seule preuve qu'il a obtenu le micro : un
    périphérique matériel déjà tenu par une autre application le fait sortir sans
    en écrire un seul, et sur une sortie d'erreur qu'on jette. Un enregistreur
    encore vivant au bout du délai est accepté — mieux vaut annoncer un micro lent
    qu'une dictée refusée.
    """
    deadline = time.monotonic() + _START_CONFIRMATION_SECONDS
    while True:
        if _captured_seconds(session) > 0.0:
            return True
        if not _recorder_alive(session):
            return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(_START_POLL_SECONDS)


def _forgotten_recorders() -> list[tuple[int, Path]]:
    """Nos `arecord` vivants que plus aucune session ne suit.

    Reconnus sur ce qu'ils écrivent : notre dossier d'exécution, et le nom
    `toggle-<horodatage>.wav` que nous seuls produisons. L'horodatage donne leur
    âge sans consulter `/proc/<pid>/stat` et ses jiffies.
    """
    prefix = os.fsencode(get_runtime_dir() / "toggle-")
    cutoff = time.time() - _ORPHAN_GRACE_SECONDS
    forgotten: list[tuple[int, Path]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # sorti entre l'énumération et la lecture
        if b"arecord" not in cmdline or prefix not in cmdline:
            continue
        audio_path = Path(os.fsdecode(cmdline.rstrip(b"\x00").rsplit(b"\x00", 1)[-1]))
        try:
            started_at = int(audio_path.stem.rsplit("-", 1)[-1]) / 1000
        except ValueError:
            continue
        if started_at <= cutoff:
            forgotten.append((int(entry.name), audio_path))
    return forgotten


def _reap_forgotten_recorders() -> int:
    """Arrêter les enregistreurs que plus aucune session ne suit. Rend leur nombre.

    Quatre fois en quatre jours, un `arecord` est resté vivant sans session, et le
    journal du raccourci n'en garde aucune trace : la cause exacte n'est pas
    établie. Le micro configuré étant ouvert en accès exclusif (`-D plughw:`), ce
    résidu refusait toute dictée jusqu'à son plafond de cinq minutes, en accusant
    « une autre application ». Le ramasser rend la panne sans conséquence, quelle
    qu'en soit l'origine — et c'est la seule protection qui vaille aussi pour les
    variantes qu'on n'a pas encore vues.

    Appelé seulement quand aucune session n'est active : ce qu'une session suit
    encore n'est pas un oubli, c'est la dictée en cours.
    """
    forgotten = _forgotten_recorders()
    if not forgotten:
        return 0
    for pid, _ in forgotten:
        try:
            # Le PID seul, pas son groupe : on vise un processus qu'on vient
            # d'identifier par sa ligne de commande, rien de ce qui l'entoure.
            # SIGINT comme `_stop_recorder`, pour qu'il finalise son en-tête.
            os.kill(pid, signal.SIGINT)
        except OSError:
            continue
    # Le fichier reste : il porte de la voix, et `/run` se vide à la déconnexion.
    # Attendre qu'ils rendent le micro, sinon le `Popen` juste derrière le
    # retrouve occupé et échoue sur le résidu qu'on vient de fermer.
    deadline = time.monotonic() + _ORPHAN_EXIT_SECONDS
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid, _ in forgotten):
            break
        time.sleep(_START_POLL_SECONDS)
    return len(forgotten)


def start_toggle_recording(
    sample_rate: int = 16000,
    device: str | None = None,
    max_seconds: int = 300,
) -> RecordingSession:
    if get_active_session():
        raise ToggleSessionError("Recording is already active.")
    executable = shutil.which("arecord")
    if not executable:
        raise RecordingError("Toggle recording requires arecord from alsa-utils.")
    _clear_stale_temporaries()
    reaped = _reap_forgotten_recorders()

    audio_path = get_runtime_dir() / f"toggle-{int(time.time() * 1000)}.wav"
    command = [
        executable,
        "-q",
        *(["-D", device] if device else []),
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        # Un micro qu'on oublie ouvert enregistre jusqu'à saturer le disque.
        # `arecord` sort proprement au plafond, donc l'appui suivant retrouve
        # une session terminée et transcrit ce qui a été capté : une troncature,
        # pas une disparition.
        "-d",
        str(max_seconds),
        str(audio_path),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    session = RecordingSession(
        pid=process.pid,
        audio_path=audio_path,
        sample_rate=sample_rate,
        started_at=time.time(),
    )
    if not _claim_session(session):
        # Un autre appui a gagné la course. Abandonner le nôtre ici, ce serait
        # laisser un arecord que plus aucune session ne référence — donc que
        # plus aucun appui ne peut arrêter.
        _stop_recorder(session)
        audio_path.unlink(missing_ok=True)
        raise ToggleSessionError("Recording is already active.")
    if not _capture_confirmed(session):
        # Gagner la course avec un enregistreur déjà mort annoncerait une dictée
        # qui n'a jamais commencé. arecord écrit son refus sur une sortie qu'on
        # jette : c'est ici, et seulement ici, qu'il peut devenir visible.
        get_session_path().unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        # Quatre fois sur quatre, l'application qui tenait le micro était Aparté.
        # Accuser un tiers quand on vient soi-même de fermer un résidu envoie
        # chercher la panne à l'endroit où elle n'est pas.
        raise RecordingError(
            "Could not start recording: the microphone was still busy just after "
            "closing a recorder Aparté had left open."
            if reaped
            else "Could not start recording. Another application may be holding the microphone."
        )
    return session


def stop_toggle_recording(timeout: float = 3.0) -> RecordingSession:
    session = get_active_session()
    if not session:
        raise ToggleSessionError("No active toggle recording.")

    # Une session peut déjà être terminée — plafond atteint — auquel cas il n'y
    # a rien à signaler : `_stop_recorder` le voit et ne touche à rien.
    _stop_recorder(session)

    deadline = time.time() + timeout
    while time.time() < deadline and _recorder_alive(session):
        time.sleep(0.05)
    _stop_recorder(session, signal.SIGTERM)

    get_session_path().unlink(missing_ok=True)
    if not session.audio_path.exists():
        raise ToggleSessionError(f"Recording file was not created: {session.audio_path}")
    return session
