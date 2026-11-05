"""Verify all 69 basic criteria against fresh, individually recorded test outcomes."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def source_digest(root):
    digest = hashlib.sha256()
    paths = [root / "manage.py", root / "tests/acceptance_basic.json"]
    for directory in ["apps", "config", "scripts", "static", "templates", "tests"]:
        paths.extend(p for p in (root / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts
                     and p.suffix in {".py", ".js", ".mjs", ".css", ".html"})
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify(root, report):
    manifest = json.loads((root / "tests/acceptance_basic.json").read_text())
    spec = next(p for p in (root / "docs").glob("*.md")
                if unicodedata.normalize("NFC", p.name) == "TM_고객관리_개발설계서.md")
    source = spec.read_text()
    section = source.split("## 18. 필수 검수 기준", 1)[1].split("### 18.8", 1)[0]
    expected = re.findall(r"^- \[ \] (.+)$", section, re.M)
    assert len(expected) == 69 and [row["criterion"] for row in manifest] == expected, "검수 문구/순서 불일치"
    assert len({row["id"] for row in manifest}) == 69, "검수 ID 중복"
    assert report["source_unchanged_during_run"] and report["source_digest"] == source_digest(root), "검사 이후 소스 변경: 재실행 필요"
    rows = []
    for entry in manifest:
        evidence = entry["tests"]
        assert evidence and len(set(evidence)) == len(evidence), entry["id"]
        statuses = {name: report["outcomes"].get(name, "not_run") for name in evidence}
        rows.append({**entry, "status": "passed" if all(v == "passed" for v in statuses.values()) else "incomplete", "evidence": statuses})
    return {"finished_at": report["finished_at"], "source_digest": report["source_digest"],
            "suite_successful": report["successful"], "tests_run": report["tests_run"],
            "total": len(rows), "passed": sum(row["status"] == "passed" for row in rows), "items": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=".local/p8-test-results.json")
    parser.add_argument("--output", default=".local/p8-acceptance.json")
    parser.add_argument("--markdown", default="docs/P8_ACCEPTANCE.md")
    parser.add_argument("--stage", choices=["P8","P9"], default="P8")
    args = parser.parse_args()
    result = verify(ROOT, json.loads((ROOT / args.results).read_text()))
    (ROOT / args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    text = [f"# {args.stage} 기본 업무 69항목 검수 결과", "", f"실행 완료 시각(UTC): `{result['finished_at']}`. 실제 실행한 Django {result['tests_run']}개 결과와 동일 소스 SHA를 대조했다.", "",
            "미실행·실패·skip·소스 변경을 통과로 처리하지 않는다. 자동 테스트 수와 검수 문항 수는 다르다.", "", "| ID | 설계서 검수 항목 | 결과 | 실행한 테스트 ID |", "|---|---|---|---|"]
    for row in result["items"]:
        text.append(f"| {row['id']} | {row['criterion']} | {'통과' if row['status'] == 'passed' else '미완료'} | " + "<br>".join(f"`{name}`" for name in row["tests"]) + " |")
    text += ["", f"**{result['passed']}/{result['total']}항목 통과.** 원시 근거: `{args.results}`, `{args.output}`. 재실행 방법과 제한은 [{args.stage}_VERIFICATION.md]({args.stage}_VERIFICATION.md)를 따른다.", ""]
    (ROOT / args.markdown).write_text("\n".join(text))
    print(json.dumps({k: result[k] for k in ["tests_run", "suite_successful", "total", "passed"]}))
    return 0 if result["suite_successful"] and result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
