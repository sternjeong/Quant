"""Inject synthetic Telegram update through real queue and real Codex CLI; isolated local git remote."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from runner import Service

os.umask(0o077)
root = Path(tempfile.mkdtemp(prefix='telegram-codex-smoke-'))
repo = root/'project'
remote = root/'remote.git'
subprocess.run(['git','init','--bare',str(remote)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['git','init',str(repo)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for args in (['config','user.name','Pipeline smoke'], ['config','user.email','smoke@example.invalid'],
             ['remote','add','origin',str(remote)]):
    subprocess.run(['git','-C',str(repo),*args],check=True)
(repo/'README.md').write_text('Isolated infrastructure smoke test.\n')
subprocess.run(['git','-C',str(repo),'add','README.md'],check=True)
subprocess.run(['git','-C',str(repo),'commit','-m','Initialize test'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['git','-C',str(repo),'push','-u','origin','HEAD'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
cli = Path(__file__).resolve().parents[2]/'.codex-telegram-runtime/node_modules/.bin/codex'
s = Service({'state_dir':str(root/'state'),'default_project':'test','projects':{'test':str(repo)},'codex_bin':str(cli),
             'codex_home':os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))})
s.chat='123'
s.ingest([{'update_id':1,'message':{'chat':{'id':123,'type':'private'},'text':
    '이 임시 저장소에 SMOKE_OK.txt 파일을 만들고 telegram pipeline ok 라고 적어라. 테스트 후 이 로컬 origin에 commit + push하고 RESUME_NOTE.md를 삭제해라. 외부 텔레그램 호출은 래퍼가 처리한다.'}}])
s.work_once()
with s.db() as db:
    row=db.execute('SELECT status, attempts FROM jobs').fetchone()
print(json.dumps({'directory':str(root),'status':row['status'],'attempts':row['attempts'], 'artifact':(repo/'SMOKE_OK.txt').exists()}))
if row['status']=='done':
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'])
    pushed=subprocess.check_output(['git','--git-dir',str(remote),'rev-parse','HEAD'])
    assert head==pushed and (repo/'SMOKE_OK.txt').exists()
elif row['status']=='retry':
    # This verifies interruption handling, not successful task completion.
    assert (repo/'RESUME_NOTE.md').exists()
    print('INCOMPLETE: retry scheduled; successful completion has not been verified')
    raise SystemExit(2)
else:
    raise SystemExit(1)
