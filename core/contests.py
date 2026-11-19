"""AI 대회 관리 — 대회별 작업 폴더·GitHub private 저장소·마감 알림 (2026-09-26, docs/AI_CONTESTS.md).

대회 하나 = CONTESTS_ROOT/<slug>/ 폴더 하나 = GitHub private 저장소 하나(contest-<slug>).
대회 정보는 그 폴더의 contest.json 이 원본이다(저장소에 함께 커밋되므로 대회 코드와 정보가 같이 다닌다).

폴더 권한(deploy/setup_contests.sh 가 한 번 설정):
- CONTESTS_ROOT 는 그룹 contests(ubuntu·quant) 소유, setgid(2775). 허브(quant)가 만들고 code-server(ubuntu)가 편집한다.
- 저장소는 `git init --shared=group` 이라 두 계정 모두 커밋할 수 있다.
GitHub 저장소는 VM 에 로그인된 gh(quant 계정)로 만든다. 실패해도 로컬 폴더는 남고 repo_status 에 사유를 남겨 다시 시도할 수 있다.
이 모듈은 주문·전략 엔진과 무관하다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

CONTESTS_ROOT = Path(os.environ.get("QUANT_CONTESTS_ROOT", "/srv/contests"))
KST = timezone(timedelta(hours=9))
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
REPO_PREFIX = "contest-"
STATUSES = ("준비", "진행", "제출 완료", "종료")
PLATFORMS = ("Kaggle", "Dacon", "AIcrowd", "DrivenData", "Zindi", "기타")
ALERT_DAYS = (7, 1, 0)
ALERT_STATE = Path(__file__).resolve().parent.parent / "data" / "contest_alerts.json"
GH_BIN = os.environ.get("GH_BIN", "/usr/bin/gh")


class ContestError(ValueError):
    pass


@dataclass
class Contest:
    slug: str
    title: str
    platform: str = "기타"
    url: str = ""
    deadline: str = ""          # YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM (KST)
    status: str = "준비"
    memo: str = ""
    repo: str = ""              # owner/name
    repo_status: str = "pending"  # pending | created | failed:<사유>
    created_at: str = ""

    @property
    def path(self) -> Path:
        return CONTESTS_ROOT / self.slug

    def deadline_dt(self) -> Optional[datetime]:
        if not self.deadline:
            return None
        try:
            if "T" in self.deadline:
                return datetime.fromisoformat(self.deadline).replace(tzinfo=KST)
            return datetime.combine(date.fromisoformat(self.deadline), datetime.max.time()).replace(tzinfo=KST)
        except ValueError:
            return None

    def days_left(self, now: Optional[datetime] = None) -> Optional[int]:
        dl = self.deadline_dt()
        if dl is None:
            return None
        return (dl.date() - (now or datetime.now(KST)).astimezone(KST).date()).days

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in ("slug", "title", "platform", "url", "deadline", "status", "memo",
                                              "repo", "repo_status", "created_at")}


# ---------------------------------------------------------------- 검증
def validate_fields(slug: str, title: str, platform: str, url: str, deadline: str, status: str = "준비") -> None:
    errs = []
    if not SLUG_RE.match(slug or ""):
        errs.append("폴더 이름: 영문 소문자·숫자·하이픈 2~41자(예: kaggle-titanic)")
    if not (title or "").strip() or len(title) > 120:
        errs.append("대회 이름: 1~120자")
    if platform not in PLATFORMS:
        errs.append(f"플랫폼: {', '.join(PLATFORMS)} 중 하나")
    if url and not re.match(r"^https?://", url):
        errs.append("대회 링크: http(s):// 로 시작")
    if deadline and Contest(slug="x", title="x", deadline=deadline).deadline_dt() is None:
        errs.append("마감: YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM")
    if status not in STATUSES:
        errs.append(f"상태: {', '.join(STATUSES)} 중 하나")
    if errs:
        raise ContestError("; ".join(errs))


# ---------------------------------------------------------------- 읽기·쓰기
def load(slug: str, root: Optional[Path] = None) -> Optional[Contest]:
    root = root or CONTESTS_ROOT
    if not SLUG_RE.match(slug or ""):
        return None
    try:
        data = json.loads((root / slug / "contest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fields = {k: v for k, v in data.items() if k in Contest.__dataclass_fields__}
    fields["slug"] = slug
    return Contest(**fields)


def list_contests(root: Optional[Path] = None, now: Optional[datetime] = None) -> list[Contest]:
    root = root or CONTESTS_ROOT
    try:
        dirs = [p for p in root.iterdir() if p.is_dir() and SLUG_RE.match(p.name)]
    except OSError:
        return []
    items = [c for c in (load(p.name, root) for p in dirs) if c]
    active = [c for c in items if c.status != "종료"]
    done = [c for c in items if c.status == "종료"]
    key = lambda c: (c.days_left(now) is None, c.days_left(now) if c.days_left(now) is not None else 0, c.slug)  # noqa: E731
    return sorted(active, key=key) + sorted(done, key=lambda c: c.slug)


def save(c: Contest, root: Optional[Path] = None) -> None:
    root = root or CONTESTS_ROOT
    path = root / c.slug / "contest.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(c.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o664)
    tmp.replace(path)


def update(slug: str, *, root: Optional[Path] = None, **fields) -> Contest:
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    for k in ("title", "platform", "url", "deadline", "status", "memo"):
        if k in fields and fields[k] is not None:
            setattr(c, k, str(fields[k]).strip())
    validate_fields(c.slug, c.title, c.platform, c.url, c.deadline, c.status)
    save(c, root)
    return c


def root_status(root: Optional[Path] = None) -> tuple[bool, str]:
    """대회 폴더를 만들 수 있는가. 아니면 사람이 할 일을 돌려준다."""
    root = root or CONTESTS_ROOT
    if not root.is_dir():
        return False, f"{root} 가 없습니다. code-server 터미널에서 한 번: sudo bash /opt/quant/deploy/setup_contests.sh"
    if not os.access(root, os.W_OK | os.X_OK):
        return False, f"{root} 에 쓸 권한이 없습니다. sudo bash /opt/quant/deploy/setup_contests.sh 를 다시 실행하세요."
    return True, "ok"


# ---------------------------------------------------------------- 생성
GITIGNORE = """# 대회 데이터·산출물은 용량·규정 때문에 커밋하지 않는다
data/
!data/.gitkeep
submissions/*
!submissions/.gitkeep
*.zip
*.parquet
*.pkl
*.pt
*.ckpt
.ipynb_checkpoints/
__pycache__/
.venv/
.env
"""


def _readme(c: Contest) -> str:
    return (f"# {c.title}\n\n- 플랫폼: {c.platform}\n- 링크: {c.url or '—'}\n- 마감: {c.deadline or '—'} (KST)\n\n"
            "## 구조\n- `data/` 대회 데이터(커밋 안 함)\n- `notebooks/` 탐색\n- `src/` 재사용 코드\n"
            "- `submissions/` 제출 파일(커밋 안 함)\n- `contest.json` 관제 센터가 읽는 대회 정보\n\n"
            "## 메모\n" + (c.memo or "") + "\n")


def scaffold(c: Contest) -> None:
    d = c.path
    for sub in ("data", "notebooks", "src", "submissions"):
        (d / sub).mkdir(parents=True, exist_ok=True)
        (d / sub / ".gitkeep").touch()
    (d / "README.md").write_text(_readme(c), encoding="utf-8")
    (d / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (d / "requirements.txt").write_text("numpy\npandas\nscikit-learn\nmatplotlib\njupyter\n", encoding="utf-8")
    (d / "src" / "__init__.py").touch()
    save(c, d.parent)


Runner = Callable[..., subprocess.CompletedProcess]


def _run(cmd: list[str], cwd: Path, runner: Runner = subprocess.run, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return runner(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def git_init(c: Contest, runner: Runner = subprocess.run) -> None:
    d = c.path
    steps = [["git", "init", "-q", "--shared=group", "-b", "main"],
             ["git", "config", "user.name", os.environ.get("CONTEST_GIT_NAME", "quant-hub")],
             ["git", "config", "user.email", os.environ.get("CONTEST_GIT_EMAIL", "quant-hub@localhost")],
             ["git", "add", "-A"], ["git", "commit", "-q", "-m", f"Start {c.title}"]]
    for cmd in steps:
        p = _run(cmd, d, runner)
        if p.returncode != 0:
            raise ContestError(f"{' '.join(cmd[:3])} 실패: {(p.stderr or p.stdout).strip()[:200]}")


def gh_owner(runner: Runner = subprocess.run) -> Optional[str]:
    try:
        p = _run([GH_BIN, "api", "user", "--jq", ".login"], Path("/"), runner, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def create_repo(slug: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run) -> Contest:
    """GitHub private 저장소를 만들고 푸시한다. 이미 created 면 그대로. 실패해도 예외 대신 repo_status 에 남긴다."""
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    if c.repo_status == "created":
        return c
    owner = gh_owner(runner)
    if not owner:
        c.repo_status = "failed:gh 로그인 확인 실패(VM 의 quant 계정에서 gh auth status)"
        save(c, root)
        return c
    name = f"{owner}/{REPO_PREFIX}{slug}"
    try:
        p = _run([GH_BIN, "repo", "create", name, "--private", "--source", str(c.path), "--remote", "origin", "--push"],
                 c.path, runner, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        p = subprocess.CompletedProcess([], 1, "", f"{type(exc).__name__}")
    if p.returncode == 0:
        c.repo, c.repo_status = name, "created"
    else:
        c.repo_status = "failed:" + (p.stderr or p.stdout or "gh repo create 실패").strip()[:200]
    save(c, root)
    return c


# ---------------------------------------------------------------- 삭제 (2026-11-12)
# 폴더는 바로 지우지 않고 CONTESTS_ROOT/.trash/<slug>-<시각> 으로 옮긴다: 폴더 안에 허브(quant)가 지울 수 없는
# ubuntu 소유 파일이 섞여 있어 rm 은 반쯤 지운 상태를 남기고, 옮기기는 맨 위 폴더 권한만 있으면 된다.
# 휴지통은 root 타이머(deploy/contests_trash)가 TRASH_DAYS 일 뒤 완전히 지운다. 그 전에는 mv 로 되살릴 수 있다.
TRASH_DIR = ".trash"
TRASH_DAYS = 7


def delete_preview(slug: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run) -> dict:
    """삭제 확인 화면용: 저장소 이름과 아직 GitHub 에 없는 작업(커밋 안 한 파일·푸시 안 한 커밋)."""
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    info = {"repo": c.repo if c.repo_status == "created" else "", "dirty": None, "unpushed": None}
    git = ["git", "-c", f"safe.directory={c.path}"]
    try:
        p = _run(git + ["status", "--porcelain"], c.path, runner, timeout=30)
        if p.returncode == 0:
            info["dirty"] = len([ln for ln in p.stdout.splitlines() if ln.strip()])
        p = _run(git + ["rev-list", "--count", "@{u}..HEAD"], c.path, runner, timeout=30)
        if p.returncode == 0:
            info["unpushed"] = int(p.stdout.strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return info


def trash_local(slug: str, *, root: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """VM 폴더를 휴지통으로 옮긴다(GitHub 저장소는 그대로). 옮긴 경로를 돌려준다."""
    root = root or CONTESTS_ROOT
    if load(slug, root) is None:
        raise ContestError(f"대회 없음: {slug}")
    trash = root / TRASH_DIR
    trash.mkdir(exist_ok=True)
    dest = trash / f"{slug}-{(now or datetime.now(KST)):%Y%m%d-%H%M%S}"
    try:
        os.rename(root / slug, dest)
    except OSError as exc:
        raise ContestError(f"폴더를 휴지통으로 옮기지 못했습니다: {exc}") from exc
    return dest


def delete_repo(slug: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run) -> str:
    """GitHub 저장소를 지운다. 이 허브가 만든 이름(<owner>/contest-<slug>)만 지운다. 지운 저장소 이름을 돌려준다."""
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    if c.repo_status != "created" or not c.repo:
        return ""
    if not re.fullmatch(rf"[A-Za-z0-9-]+/{re.escape(REPO_PREFIX + slug)}", c.repo):
        raise ContestError(f"이 허브가 만든 저장소 이름이 아니라 지우지 않습니다: {c.repo}")
    try:
        p = _run([GH_BIN, "repo", "delete", c.repo, "--yes"], Path("/"), runner, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContestError(f"저장소 삭제 실패: {type(exc).__name__}") from exc
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        if "delete_repo" in err:
            err = ("GitHub 토큰에 삭제 권한(delete_repo)이 없습니다. VM 에서 한 번: "
                   "sudo -u quant -H gh auth refresh -h github.com -s delete_repo")
        raise ContestError("저장소 삭제 실패: " + err[:300])
    return c.repo


def delete_contest(slug: str, mode: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run,
                   now: Optional[datetime] = None) -> str:
    """mode='local': VM 폴더만 휴지통으로. mode='all': GitHub 저장소를 먼저 지우고(실패하면 폴더도 그대로) 폴더를 휴지통으로."""
    if mode not in ("local", "all"):
        raise ContestError("알 수 없는 삭제 방식")
    repo = delete_repo(slug, root=root, runner=runner) if mode == "all" else ""
    dest = trash_local(slug, root=root, now=now)
    head = f"GitHub 저장소 {repo} 삭제, " if repo else ""
    return f"{head}VM 폴더를 휴지통({dest.name})으로 옮겼습니다. {TRASH_DAYS}일 뒤 완전히 지워집니다."


# ---------------------------------------------------------------- 완료 = GitHub 반영 확인 후 VM 폴더 정리 (2026-11-19)
# '완료'는 GitHub 에 모든 작업이 올라가 있는지 확인한 뒤에만 VM 폴더를 휴지통으로 옮긴다:
#   1) contest.json(허브가 고친 상태값)을 커밋, 2) 커밋 안 한 파일이 있으면 멈춤(사용자가 '모두 커밋' 을 고르면 커밋),
#   3) 모든 로컬 브랜치를 푸시, 4) fetch 후 각 브랜치가 origin 에 들어 있는지(조상인지) 확인, 5) 기록을 .archive 에 남기고 휴지통.
# git 제외 파일(data/·submissions/·모델 파일 등)은 GitHub 에 없으므로 확인 화면에서 크기와 함께 알린다.
ARCHIVE_DIR = ".archive"


def _git(c: Contest) -> list[str]:
    return ["git", "-c", f"safe.directory={c.path}", "-c", "core.quotepath=off"]


def _ok(c: Contest, args: list[str], runner: Runner, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return _run(_git(c) + args, c.path, runner, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 1, "", type(exc).__name__)


def _size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
        return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())
    except OSError:
        return 0


def sync_check(slug: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run, fetch: bool = True) -> dict:
    """GitHub 반영 상태. {'repo','error','dirty':[(경로,바이트)],'unpushed':{브랜치: 개수|None(원격에 없음)},
    'stash': n, 'ignored':[(경로,바이트)]}. error 가 있으면 확인 자체를 못 한 것(삭제 금지)."""
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    info: dict = {"repo": c.repo if c.repo_status == "created" else "", "error": "", "dirty": [], "unpushed": {},
                  "stash": 0, "ignored": []}
    if not info["repo"]:
        info["error"] = "연결된 GitHub 저장소가 없습니다(대회 화면에서 '저장소 다시 만들기' 먼저)."
        return info
    if fetch:
        p = _ok(c, ["fetch", "-q", "--prune", "origin"], runner, timeout=120)
        if p.returncode != 0:
            info["error"] = "GitHub 에서 최신 상태를 받지 못했습니다: " + (p.stderr or p.stdout).strip()[:200]
            return info
    p = _ok(c, ["status", "--porcelain", "-z", "--ignored", "--untracked-files=normal"], runner)
    if p.returncode != 0:
        info["error"] = "git status 실패: " + (p.stderr or p.stdout).strip()[:200]
        return info
    entries = p.stdout.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        code, rel = e[:2], e[3:]
        if code[0] in "RC":
            i += 1  # 이름 바꾸기는 원래 이름이 다음 항목으로 온다
        if rel == "contest.json" and code != "!!":
            continue  # 허브가 고친 상태값 — 완료할 때 허브가 직접 커밋한다
        size = _size(c.path / rel)
        (info["ignored"] if code == "!!" else info["dirty"]).append((rel, size))
    info["ignored"] = sorted((x for x in info["ignored"] if "__pycache__" not in x[0] and ".ipynb_checkpoints" not in x[0]),
                             key=lambda x: -x[1])  # 폴더 단위로 묶여 온다(.venv/ 등) — 큰 것부터
    p = _ok(c, ["for-each-ref", "refs/heads", "--format=%(refname:short)"], runner)
    for branch in p.stdout.split():
        has_remote = _ok(c, ["rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}"], runner).returncode == 0
        if not has_remote:
            info["unpushed"][branch] = None
            continue
        q = _ok(c, ["rev-list", "--count", f"origin/{branch}..{branch}"], runner)
        n = int(q.stdout.strip() or 0) if q.returncode == 0 else -1
        if n:
            info["unpushed"][branch] = n
    p = _ok(c, ["stash", "list"], runner)
    info["stash"] = len([ln for ln in p.stdout.splitlines() if ln.strip()])
    return info


def archive_contest(slug: str, *, commit_all: bool = False, root: Optional[Path] = None,
                    runner: Runner = subprocess.run, now: Optional[datetime] = None) -> str:
    """완료: GitHub 에 다 올라간 것을 확인한 뒤 VM 폴더를 휴지통으로. 하나라도 확인이 안 되면 ContestError(폴더 그대로)."""
    root = root or CONTESTS_ROOT
    c = load(slug, root)
    if c is None:
        raise ContestError(f"대회 없음: {slug}")
    if c.repo_status != "created" or not c.repo:
        raise ContestError("연결된 GitHub 저장소가 없어 지우지 않았습니다. 대회 화면에서 저장소를 먼저 만드세요.")
    prev = c.status
    try:
        return _archive(c, commit_all, root, runner, now)
    except ContestError:
        if load(slug, root) is not None:  # 폴더가 남아 있으면 상태를 원래대로(목록에 계속 보이게)
            c.status = prev
            save(c, root)
        raise


def _archive(c: Contest, commit_all: bool, root: Path, runner: Runner, now: Optional[datetime]) -> str:
    slug = c.slug
    c.status = "종료"
    save(c, root)
    _ok(c, ["add", "contest.json"], runner)
    if _ok(c, ["diff", "--cached", "--quiet"], runner).returncode != 0:
        p = _ok(c, ["commit", "-q", "-m", "contest.json: 상태 종료(관제 센터 '완료')"], runner)
        if p.returncode != 0:
            raise ContestError("contest.json 커밋 실패: " + (p.stderr or p.stdout).strip()[:200])
    info = sync_check(slug, root=root, runner=runner, fetch=False)
    if info["dirty"]:
        if not commit_all:
            raise ContestError(f"커밋하지 않은 파일 {len(info['dirty'])}개가 있어 지우지 않았습니다.")
        for cmd in (["add", "-A"], ["commit", "-q", "-m", "완료 전 남은 작업 모두 커밋(관제 센터 '완료')"]):
            p = _ok(c, cmd, runner, timeout=120)
            if p.returncode != 0:
                raise ContestError(f"git {cmd[0]} 실패: " + (p.stderr or p.stdout).strip()[:200])
    if info["stash"]:
        raise ContestError(f"git stash 에 보관한 작업 {info['stash']}개가 있습니다(GitHub 에 올라가지 않음). "
                           "VS Code 에서 꺼내 커밋하거나 지운 뒤 다시 누르세요.")
    p = _ok(c, ["for-each-ref", "refs/heads", "--format=%(refname:short)"], runner)
    branches = p.stdout.split()
    if branches:
        p = _ok(c, ["push", "-q", "origin", *[f"refs/heads/{b}:refs/heads/{b}" for b in branches]], runner, timeout=300)
        if p.returncode != 0:
            raise ContestError("GitHub 푸시 실패 — 지우지 않았습니다: " + (p.stderr or p.stdout).strip()[:300])
    # 푸시가 성공했다고 믿지 않고 GitHub 에서 다시 받아 각 브랜치가 들어 있는지 확인한다.
    after = sync_check(slug, root=root, runner=runner, fetch=True)
    problems = []
    if after["error"]:
        problems.append(after["error"])
    if after["dirty"]:
        problems.append(f"커밋 안 한 파일 {len(after['dirty'])}개")
    for b, n in after["unpushed"].items():
        problems.append(f"브랜치 {b}: " + ("GitHub 에 없음" if n is None else f"푸시 안 된 커밋 {n}개"))
    if problems:
        raise ContestError("GitHub 반영을 확인하지 못해 지우지 않았습니다: " + "; ".join(problems))
    head = _ok(c, ["rev-parse", "HEAD"], runner).stdout.strip()
    origin = _ok(c, ["remote", "get-url", "origin"], runner).stdout.strip()
    record = {**c.to_json(), "archived_at": (now or datetime.now(KST)).isoformat(timespec="seconds"),
              "head": head, "origin_url": origin, "branches": branches, "ignored_bytes": sum(sz for _, sz in after["ignored"])}
    arch = root / ARCHIVE_DIR
    arch.mkdir(exist_ok=True)
    (arch / f"{slug}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dest = trash_local(slug, root=root, now=now)
    return (f"'{c.title}' 완료 — GitHub {c.repo} 에 브랜치 {len(branches)}개 모두 반영된 것을 확인하고 VM 폴더를 "
            f"휴지통({dest.name})으로 옮겼습니다. {TRASH_DAYS}일 뒤 완전히 지워집니다.")


def list_archived(root: Optional[Path] = None) -> list[dict]:
    root = root or CONTESTS_ROOT
    out = []
    try:
        files = sorted((root / ARCHIVE_DIR).glob("*.json"))
    except OSError:
        return []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("archived_at", ""), reverse=True)


def restore_archived(slug: str, *, root: Optional[Path] = None, runner: Runner = subprocess.run) -> Contest:
    """되돌리기: GitHub 에서 다시 clone 하고 상태를 '진행'으로. git 제외 파일(data/ 등)은 돌아오지 않는다."""
    root = root or CONTESTS_ROOT
    rec_path = root / ARCHIVE_DIR / f"{slug}.json"
    if not SLUG_RE.match(slug or "") or not rec_path.exists():
        raise ContestError(f"완료 기록 없음: {slug}")
    if (root / slug).exists():
        raise ContestError(f"이미 같은 이름의 폴더가 있습니다: {slug}")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    url = rec.get("origin_url") or ""
    if not url and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", rec.get("repo", "")):
        url = f"https://github.com/{rec['repo']}.git"
    if not url or url.startswith("-"):
        raise ContestError("기록에 저장소 주소가 없습니다.")
    old = os.umask(0o002)
    try:
        p = _run(["git", "clone", "-q", "--config", "core.sharedRepository=group", "--", url, str(root / slug)], root, runner, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        p = subprocess.CompletedProcess([], 1, "", type(exc).__name__)
    finally:
        os.umask(old)
    if p.returncode != 0:
        raise ContestError("GitHub 에서 받지 못했습니다: " + (p.stderr or p.stdout).strip()[:200])
    c = update(slug, root=root, status="진행")
    rec_path.unlink(missing_ok=True)
    return c


def create_contest(slug: str, title: str, platform: str, url: str = "", deadline: str = "", memo: str = "", *,
                   root: Optional[Path] = None, runner: Runner = subprocess.run) -> Contest:
    root = root or CONTESTS_ROOT
    validate_fields(slug, title, platform, url, deadline)
    ok, why = root_status(root)
    if not ok:
        raise ContestError(why)
    if (root / slug).exists():
        raise ContestError(f"이미 있는 폴더: {slug}")
    old = os.umask(0o002)  # 그룹(contests)도 쓸 수 있게
    try:
        c = Contest(slug=slug, title=title.strip(), platform=platform, url=url.strip(), deadline=deadline.strip(),
                    memo=memo.strip(), created_at=datetime.now(KST).isoformat(timespec="seconds"))
        (root / slug).mkdir()
        scaffold(c)
        git_init(c, runner)
    finally:
        os.umask(old)
    return create_repo(slug, root=root, runner=runner)


def code_server_url(c: Contest, base: str) -> str:
    from urllib.parse import quote

    return base.rstrip("/") + "/?folder=" + quote(str(c.path))


# ---------------------------------------------------------------- 마감 알림
def due_alerts(contests: list[Contest], sent: dict, now: Optional[datetime] = None) -> list[tuple[str, int, Contest]]:
    """(키, 남은 일수, 대회). 키마다 한 번만. 종료·제출 완료된 대회는 알리지 않는다."""
    out = []
    for c in contests:
        if c.status in ("종료", "제출 완료"):
            continue
        left = c.days_left(now)
        if left is None:
            continue
        if left < 0:
            continue
        # 남은 일수 이상인 단계 중 가장 가까운 것 하나(D-1 이면 1, D-3 이면 7).
        stage = min((d for d in ALERT_DAYS if d >= left), default=None)
        key = f"{c.slug}:{c.deadline}:{stage}"
        if stage is not None and key not in sent:
            out.append((key, left, c))
    return out


def run_deadline_alerts(*, root: Optional[Path] = None, now: Optional[datetime] = None,
                        notify: Optional[Callable[[str], Any]] = None, state_path: Optional[Path] = None) -> dict:
    state_path = state_path or ALERT_STATE
    try:
        sent = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = {}
    alerts = due_alerts(list_contests(root, now), sent, now)
    for key, left, c in alerts:
        when = "오늘 마감" if left == 0 else f"마감 D-{left}"
        msg = f"[AI 대회] {c.title} — {when} ({c.deadline} KST)\n상태: {c.status}" + (f"\n{c.url}" if c.url else "")
        if notify is None or notify(msg) is not False:
            # 같은 키로는 다시 보내지 않는다. 마감 이전 단계 키도 함께 막아 D-7 을 놓쳤을 때 D-7·D-1 이 겹쳐 오지 않게 한다.
            for d in ALERT_DAYS:
                if d >= left:
                    sent[f"{c.slug}:{c.deadline}:{d}"] = datetime.now(KST).isoformat(timespec="seconds")
    if alerts:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(sent, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"sent": [k for k, _, _ in alerts], "n_contests": len(list_contests(root, now))}
