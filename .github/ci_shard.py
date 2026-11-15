"""tests/test_*.py 를 N 묶음으로 나눠 한 묶음의 파일 목록을 출력한다(.github/workflows/tests.yml 의 병렬 실행용).

파일 크기를 실행 시간의 대략적인 대리값으로 써서 큰 파일부터 가장 가벼운 묶음에 넣는다. 같은 입력이면 항상 같은 결과다.
사용: python .github/ci_shard.py <묶음 수> <묶음 번호(0부터)>
"""

import sys
from pathlib import Path


def shards(files: list[Path], n: int) -> list[list[Path]]:
    bins: list[list[Path]] = [[] for _ in range(n)]
    load = [0] * n
    for f in sorted(files, key=lambda p: (-p.stat().st_size, p.name)):
        i = load.index(min(load))
        bins[i].append(f)
        load[i] += f.stat().st_size
    return bins


if __name__ == "__main__":
    n, k = int(sys.argv[1]), int(sys.argv[2])
    tests = sorted(Path("tests").glob("test_*.py"))
    print(" ".join(str(p) for p in sorted(shards(tests, n)[k])))
