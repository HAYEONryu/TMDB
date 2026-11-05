"""Own a project-only PostgreSQL 17 cluster; never touches OS services."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".local/postgres17"
SOCKET = ROOT / ".local/pgsocket"
LOG = ROOT / ".local/postgres17.log"
PG = Path(os.environ.get("TM_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT = "55432"


def run(tool, *args, check=True, capture=False):
    return subprocess.run([str(PG / tool), *map(str, args)], check=check,
                          capture_output=capture, text=True,
                          env={**os.environ, "PGPASSWORD": "tm-local-only"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    action = parser.parse_args().action
    version = run("postgres", "--version", capture=True).stdout
    if " 17." not in version:
        raise SystemExit("TM_PG_BIN은 PostgreSQL 17을 가리켜야 합니다.")
    if action != "start":
        if not (DATA / "PG_VERSION").exists():
            raise SystemExit("프로젝트 DB가 없습니다.")
        if action == "status":
            result = run("pg_ctl", "-D", DATA, "status", check=False, capture=True)
            if result.returncode == 3:
                print("프로젝트 PostgreSQL 17: 중지 상태")
                return
            if result.returncode:
                raise SystemExit(result.stderr.strip() or "DB 상태를 확인할 수 없습니다.")
            print(result.stdout, end="")
            return
        run("pg_ctl", "-D", DATA, *(["-m", "fast", "-w", "stop"] if action == "stop" else ["status"]))
        return
    DATA.parent.mkdir(exist_ok=True)
    SOCKET.mkdir(exist_ok=True)
    if not DATA.exists():
        with tempfile.NamedTemporaryFile(mode="w", dir=DATA.parent) as password_file:
            password_file.write("tm-local-only\n")
            password_file.flush()
            run("initdb", "-D", DATA, "--username=tm", "--encoding=UTF8", "--no-locale",
                "--auth-local=trust", "--auth-host=scram-sha-256", f"--pwfile={password_file.name}")
    elif not (DATA / "PG_VERSION").exists():
        raise SystemExit("기존 디렉터리가 완성된 TM 클러스터가 아닙니다. 자동 덮어쓰기를 하지 않습니다.")
    if (DATA / "PG_VERSION").read_text().strip() != "17":
        raise SystemExit("기존 클러스터 버전이 다릅니다. 자동 변경하지 않습니다.")
    if run("pg_ctl", "-D", DATA, "status", check=False, capture=True).returncode:
        run("pg_ctl", "-D", DATA, "-l", LOG, "-o", f"-p {PORT} -k {SOCKET} -c listen_addresses=127.0.0.1", "-w", "start")
    # Unix socket path ties the connection to our own cluster, not another port owner.
    exists = run("psql", "-h", SOCKET, "-p", PORT, "-U", "tm", "-d", "postgres", "-Atc",
                 "SELECT 1 FROM pg_database WHERE datname='tm_dev'", capture=True).stdout.strip()
    if not exists:
        run("createdb", "-h", SOCKET, "-p", PORT, "-U", "tm", "tm_dev")
    print("프로젝트 PostgreSQL 17 준비 완료: 127.0.0.1:55432 / tm_dev")


if __name__ == "__main__":
    main()
