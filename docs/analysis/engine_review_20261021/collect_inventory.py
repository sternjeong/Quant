"""Snapshot published result metadata without running or changing a research job."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
rows = []
for path in sorted((a.repo / 'research/results').glob('*/REPORT.md')):
    name = path.parent.name
    result_path = path.with_name('results.json')
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    definition = a.repo / 'research/jobs' / name / 'job.json'
    job = json.loads(definition.read_text()) if definition.exists() else {}
    rows.append({
        'id': name, 'title': job.get('title', name), 'revision': job.get('revision', 1),
        'verdicts': result.get('verdicts', {}), 'summary': result.get('summary'),
        'smoke': result.get('smoke'),
        'judge_version': result.get('judge_version', result.get('version')),
        'report_path': str(path),
        'report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'result_sha256': hashlib.sha256(result_path.read_bytes()).hexdigest() if result_path.exists() else None,
    })
meta = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'repo_commit': subprocess.check_output(['git', '-C', str(a.repo), 'rev-parse', 'HEAD'], text=True).strip(),
        'report_count': len(rows), 'results': rows}
a.out.mkdir(parents=True, exist_ok=True)
(a.out / 'inventory.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
lines = ['# 운영 연구 결과 전체 목록 — 2026-10-21', '',
         f'운영 코드 `{meta["repo_commit"][:7]}`, 보고서 {len(rows)}건. 원래 기계 판정은 변경하지 않았다.', '',
         '이 표는 연구 수익의 순위표가 아니다. PASS는 비교 대상·기간·지표가 다르며, '
         '계산 오류의 영향 범위는 REVIEW.md를 함께 읽어야 한다. smoke-noop는 실행기 점검이다.', '',
         '| ID | 제목 | 저장된 판정/요약 |', '|---|---|---|']
for row in rows:
    verdict = row['verdicts'] or row['summary'] or {'status': '원문 확인'}
    cell = '; '.join(f'{k}: {v}' for k, v in verdict.items())
    lines.append('| [' + row['id'] + '](' + row['report_path'] + ') | '
                 + row['title'].replace('|', '\\|') + ' | ' + cell.replace('|', '\\|').replace('\n', ' ') + ' |')
(a.out / 'INVENTORY.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'report_count': len(rows), 'files': ['inventory.json', 'INVENTORY.md']}, ensure_ascii=False))
