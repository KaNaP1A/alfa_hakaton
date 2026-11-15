"""Start restored PostgreSQL, in-process ML backend and Vite with one command."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
STATE = ROOT / ".run"
ENV_FILE = BACKEND / ".env.snapshot"
PYTHON = ROOT / ".venv" / "bin" / "python"
RUNTIME = ROOT / "models" / "runtime"


def announce(message: str) -> None:
    print(message, flush=True)


def run(args: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    # Capture command output so generated credentials never appear in diagnostics.
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        # None of the commands receive passwords as arguments.
        raise RuntimeError(
            f"Команда завершилась с ошибкой: {shlex.join(args)}\n{result.stderr[-3000:]}"
        )
    return result.stdout.strip()


def compose(*args: str) -> str:
    # Ignore inherited COMPOSE_PROFILES: migrations must require --migrate.
    env = dict(os.environ)
    env.update(load_env(ENV_FILE))
    env.pop("COMPOSE_PROFILES", None)
    return run(
        [
            "docker",
            "compose",
            "-f",
            str(BACKEND / "compose.yaml"),
            "--env-file",
            str(ENV_FILE),
            *args,
        ],
        cwd=BACKEND,
        env=env,
    )


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").partition("=")
        if not separator or not key.strip().isidentifier():
            raise RuntimeError(f"Некорректная строка {number} в {path.name}")
        tokens = shlex.split(value, comments=True)
        values[key.strip()] = " ".join(tokens)
    return values


def api_environment(values: dict[str, str], generation: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(values)
    env.update(
        {
            "ALFA_CATALOG_SOURCE": "postgres",
            "ALFA_AUTO_CREATE_TABLES": "false",
            "ALFA_RECO_MODE": "python",
            "ALFA_RECO_CATALOG": str(RUNTIME / "catalog"),
            "ALFA_CATALOG_GENERATION": generation,
            "HF_HUB_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                [str(BACKEND), str(ROOT / "05_code" / "src")]
            ),
        }
    )
    return env


def fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare_python(env: dict[str, str]) -> None:
    paths = [BACKEND / "pyproject.toml"] + [
        ROOT / "05_code" / name
        for name in (
            "requirements-relevance.txt",
            "requirements-semantic.txt",
            "requirements-rank.txt",
        )
    ]
    stamp = STATE / "python-dependencies"
    version = fingerprint(paths)
    if not PYTHON.exists():
        announce("Создаю Python 3.12 окружение…")
        run(["uv", "venv", "--python", "3.12", str(PYTHON.parent.parent)])
    if not stamp.exists() or stamp.read_text() != version:
        announce(
            "Устанавливаю зависимости API и ML (первый запуск может занять несколько минут)…"
        )
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(PYTHON),
                "-e",
                str(BACKEND),
                "-r",
                str(ROOT / "05_code" / "requirements-relevance.txt"),
            ],
            env=env,
        )
        stamp.write_text(version)


def prepare_model(env: dict[str, str]) -> str:
    source = ROOT / "models" / "recommender"
    weights = source / "encoder" / "model.safetensors"
    if not weights.exists() or weights.stat().st_size < 1024:
        announce("Загружаю веса через Git LFS…")
        run(["git", "lfs", "pull"])
    script = ROOT / "05_code" / "scripts" / "prepare_backend_bundle.py"
    if not RUNTIME.exists():
        announce("Проверяю модель и создаю отдельную runtime-копию…")
        run([str(PYTHON), str(script), "--verify", str(source)], env=env)
        with tempfile.TemporaryDirectory(
            prefix=".runtime-", dir=source.parent
        ) as directory:
            prepared = Path(directory) / "bundle"
            shutil.copytree(source, prepared)
            # Publish the complete copy, then relocate paths to its final location.
            prepared.rename(RUNTIME)
    # Verification is read-only; relocation only changes this local runtime copy.
    run([str(PYTHON), str(script), "--relocate", str(RUNTIME)], env=env)
    return str(
        json.loads((RUNTIME / "catalog" / "CURRENT.json").read_text())["generation"]
    )


def prepare_frontend() -> None:
    paths = [FRONTEND / "package.json"]
    lock = FRONTEND / "package-lock.json"
    if lock.exists():
        paths.append(lock)
    stamp = STATE / "frontend-dependencies"
    if (FRONTEND / "node_modules" / ".bin" / "vite").exists() and stamp.exists():
        if stamp.read_text() == fingerprint(paths):
            return
    announce("Устанавливаю зависимости фронтенда…")
    run(
        ["npm", "ci" if lock.exists() else "install", "--no-audit", "--no-fund"],
        cwd=FRONTEND,
    )
    if lock.exists() and lock not in paths:
        paths.append(lock)
    stamp.write_text(fingerprint(paths))


def check_port(port: int) -> None:
    with socket.socket() as probe:
        # A stopped dev server can leave accepted connections in TIME_WAIT.
        # Allow rebinding those; an active listener still makes bind fail.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(
                f"Порт {port} занят. Остановите предыдущий API/фронтенд."
            ) from error


def listening_pids(port: int) -> list[int]:
    lsof = shutil.which("lsof")
    if lsof is None:
        raise RuntimeError("Для автоматического освобождения портов требуется lsof")
    result = subprocess.run(
        [lsof, "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        text=True,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.strip()
        raise RuntimeError(f"Не удалось проверить порт {port} через lsof: {detail}")
    try:
        return sorted({int(value) for value in result.stdout.split()})
    except ValueError as error:
        raise RuntimeError(f"lsof вернул некорректный PID для порта {port}") from error


def stop_port_occupants(port: int) -> None:
    """Stop existing TCP listeners on an application port before startup."""
    for _ in range(3):
        pids = listening_pids(port)
        if not pids:
            return
        announce(
            f"Порт {port} занят (PID {', '.join(map(str, pids))}); останавливаю…"
        )
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise RuntimeError(
                    f"Нет прав остановить PID {pid} на порту {port}"
                ) from error

        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            remaining = set(listening_pids(port)) & set(pids)
            if not remaining:
                break
            time.sleep(0.1)

        remaining = set(listening_pids(port))
        if not remaining:
            return
        for pid in remaining:
            announce(f"PID {pid} не завершился; останавливаю принудительно…")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise RuntimeError(
                    f"Нет прав остановить PID {pid} на порту {port}"
                ) from error
        if remaining:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and listening_pids(port):
                time.sleep(0.1)

    remaining = listening_pids(port)
    if remaining:
        raise RuntimeError(
            f"Не удалось освободить порт {port} (PID {', '.join(map(str, remaining))})"
        )


def wait_ready(url: str, process: subprocess.Popen[str], timeout: float) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Процесс завершился до запуска {url}; смотрите логи в .run/"
            )
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Не дождался готовности {url}; смотрите логи в .run/")


def serve(env: dict[str, str]) -> None:
    processes: list[subprocess.Popen[str]] = []
    streams: list[IO[str]] = []
    try:
        for name, command, cwd, url, timeout in [
            (
                "backend",
                [
                    str(PYTHON),
                    "-m",
                    "uvicorn",
                    "app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8080",
                    "--workers",
                    "1",
                ],
                BACKEND,
                "http://127.0.0.1:8080/ready",
                300,
            ),
            (
                "frontend",
                ["npm", "run", "dev", "--", "--port", "5173", "--strictPort"],
                FRONTEND,
                "http://127.0.0.1:5173",
                60,
            ),
        ]:
            stream = (STATE / f"{name}.log").open("w", encoding="utf-8")
            streams.append(stream)
            child_env = dict(env)
            child_env.update(
                {
                    "VITE_API_PROXY_TARGET": "http://127.0.0.1:8080",
                }
            )
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=child_env,
                text=True,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            processes.append(process)
            announce(f"Запускаю {name}; лог: .run/{name}.log")
            wait_ready(url, process, timeout)
        announce(
            "\nПроект готов: http://127.0.0.1:5173\nAPI: http://127.0.0.1:8080/docs\n"
            "Ctrl+C — остановить API и фронтенд. PostgreSQL останется работать."
        )
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Один из процессов завершился; смотрите .run/*.log"
                    )
            time.sleep(1)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for output in streams:
            output.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PostgreSQL + Python ML singleton + React"
    )
    parser.add_argument(
        "--migrate", action="store_true", help="Явно применить SQL служебных таблиц API"
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Подготовить зависимости и ML без запуска API/фронтенда",
    )
    args = parser.parse_args()
    if args.migrate and args.prepare_only:
        parser.error("--prepare-only не применяется вместе с --migrate")
    for command in ("docker", "uv", "npm"):
        if shutil.which(command) is None:
            raise RuntimeError(f"Нужно установить {command}")
    if not (ROOT / "alfa_course_hackathon.backup").is_file():
        raise RuntimeError("Положите alfa_course_hackathon.backup в корень проекта")
    STATE.mkdir(exist_ok=True)
    run([sys.executable, str(BACKEND / "scripts" / "setup_snapshot_env.py")])
    values = load_env(ENV_FILE)
    if not values.get("ALFA_DATABASE_URL", "").startswith("postgresql+psycopg:"):
        raise RuntimeError("В .env.snapshot нужен ALFA_DATABASE_URL для PostgreSQL")
    # The native API must connect to this Compose database, never a different DSN.
    parsed = urlsplit(
        values["ALFA_DATABASE_URL"].replace("postgresql+psycopg:", "postgresql:", 1)
    )
    if (
        parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.path != "/alfa_snapshot"
        or parsed.username != "alfa"
        or parsed.port != int(values.get("POSTGRES_PORT", "55432"))
        or unquote(parsed.password or "") != values.get("POSTGRES_PASSWORD")
    ):
        raise RuntimeError(
            "ALFA_DATABASE_URL должен указывать на локальную alfa_snapshot"
        )
    announce("Запускаю PostgreSQL и жду восстановления снимка…")
    compose("up", "-d", "--build", "--wait", "db")
    if not args.prepare_only:
        for port in (8080, 5173):
            stop_port_occupants(port)
            check_port(port)
        if args.migrate:
            announce("Применяю SQL-миграцию служебных таблиц API (--migrate)…")
            compose("--profile", "tools", "run", "--rm", "migrate")
        installed = compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "alfa",
            "-d",
            "alfa_snapshot",
            "-Atc",
            "SELECT to_regclass('public.alfa_api_schema_migrations') IS NOT NULL",
        )
        if installed != "t":
            raise RuntimeError(
                "Служебные таблицы ещё не созданы. Для первого полного запуска: ./run.sh --migrate\n"
                "Миграции автоматически не применялись; PostgreSQL оставлен работающим."
            )
    env = api_environment(values, "preparing")
    prepare_python(env)
    generation = prepare_model(env)
    prepare_frontend()
    if args.prepare_only:
        announce(
            "Окружение и модель готовы. Миграции не применялись. Запуск: ./run.sh --migrate"
        )
        return
    serve(api_environment(values, generation))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        announce("\nAPI и фронтенд остановлены. PostgreSQL сохранён.")
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)
