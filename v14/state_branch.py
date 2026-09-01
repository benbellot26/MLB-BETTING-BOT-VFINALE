from __future__ import annotations

"""Hydrate/persist mutable Pulsar state on a dedicated Git branch.

Production code lives on ``main``. Mutable ledgers, reports and refreshed data
artifacts live on ``runtime-data``. Workflows hydrate their required state before
running and persist only explicitly named paths afterwards. This prevents routine
bot state commits from mutating the production code branch.

The helper uses local git plumbing only; it makes no network calls other than the
repository fetch/push performed by git itself and never accesses Odds/MLB APIs.
"""

import argparse
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import Iterable

DEFAULT_BRANCH=os.getenv("V14_STATE_BRANCH","runtime-data")
DEFAULT_REMOTE=os.getenv("V14_STATE_REMOTE","origin")


def _run(args:list[str],*,cwd:Path|str|None=None,check:bool=True,capture:bool=False)->subprocess.CompletedProcess:
    return subprocess.run(args,cwd=cwd,check=check,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None)


def _paths(values:Iterable[str])->list[str]:
    out=[]
    for value in values:
        item=str(value).strip().replace("\\","/").rstrip("/")
        if not item or item.startswith("/") or item.startswith("../") or "/../" in item:continue
        if item not in out:out.append(item)
    return out


def load_manifest(path:Path|str)->list[str]:
    p=Path(path)
    if not p.exists():return []
    return _paths(line.split("#",1)[0] for line in p.read_text(encoding="utf-8").splitlines())


def resolve_paths(paths:list[str]|None=None,manifest:Path|str|None=None)->list[str]:
    return _paths([*(paths or []),*(load_manifest(manifest) if manifest else [])])


def fetch_state(*,branch:str=DEFAULT_BRANCH,remote:str=DEFAULT_REMOTE)->None:
    _run(["git","fetch",remote,f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}"])


def _remote_object_type(ref:str,rel:str)->str|None:
    result=_run(["git","cat-file","-t",f"{ref}:{rel}"],check=False,capture=True)
    return result.stdout.decode().strip() if result.returncode==0 else None


def hydrate(paths:list[str],*,branch:str=DEFAULT_BRANCH,remote:str=DEFAULT_REMOTE)->dict[str,int]:
    selected=_paths(paths);fetch_state(branch=branch,remote=remote);copied=missing=0;ref=f"{remote}/{branch}"
    for rel in selected:
        kind=_remote_object_type(ref,rel)
        if kind=="blob":
            result=_run(["git","show",f"{ref}:{rel}"],capture=True);target=Path(rel);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result.stdout);copied+=1
        elif kind=="tree":
            archive=_run(["git","archive","--format=tar",ref,rel],capture=True).stdout
            # Paths come from the trusted repository tree and the caller can only
            # request relative paths. Python's data filter adds a second traversal guard.
            with tarfile.open(fileobj=BytesIO(archive),mode="r:") as tf:tf.extractall(path=".",filter="data")
            copied+=1
        else:
            missing+=1
    return {"requested":len(selected),"hydrated":copied,"missing":missing}


def persist(paths:list[str],*,message:str,branch:str=DEFAULT_BRANCH,remote:str=DEFAULT_REMOTE)->dict[str,object]:
    selected=_paths(paths)
    if not selected:return {"changed":False,"paths":0,"reason":"no paths selected"}
    fetch_state(branch=branch,remote=remote)
    root=Path.cwd().resolve()
    with tempfile.TemporaryDirectory(prefix="pulsar-state-") as tmp:
        work=Path(tmp)/"worktree"
        _run(["git","worktree","add","--detach",str(work),f"{remote}/{branch}"])
        try:
            for rel in selected:
                src=root/rel;dst=work/rel
                if src.exists():
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    if src.is_dir():
                        if dst.exists():shutil.rmtree(dst)
                        shutil.copytree(src,dst)
                    else:shutil.copy2(src,dst)
                elif dst.exists():
                    if dst.is_dir():shutil.rmtree(dst)
                    else:dst.unlink()
            _run(["git","config","user.name","Pulsar V14 State"],cwd=work)
            _run(["git","config","user.email","github-actions[bot]@users.noreply.github.com"],cwd=work)
            _run(["git","add","-A","--",*selected],cwd=work)
            diff=_run(["git","diff","--cached","--quiet"],cwd=work,check=False)
            if diff.returncode==0:return {"changed":False,"paths":len(selected),"branch":branch}
            _run(["git","commit","-m",message],cwd=work)
            sha=_run(["git","rev-parse","HEAD"],cwd=work,capture=True).stdout.decode().strip()
            _run(["git","push",remote,f"HEAD:refs/heads/{branch}"],cwd=work)
            return {"changed":True,"paths":len(selected),"branch":branch,"commit":sha}
        finally:
            _run(["git","worktree","remove","--force",str(work)],check=False)


def main()->None:
    parser=argparse.ArgumentParser(description="Hydrate/persist Pulsar mutable state on runtime-data")
    parser.add_argument("command",choices=("hydrate","persist"));parser.add_argument("--branch",default=DEFAULT_BRANCH);parser.add_argument("--remote",default=DEFAULT_REMOTE);parser.add_argument("--manifest");parser.add_argument("--path",action="append",default=[]);parser.add_argument("--message",default="data: persist Pulsar V14 runtime state [skip ci]")
    args=parser.parse_args();paths=resolve_paths(args.path,args.manifest)
    out=hydrate(paths,branch=args.branch,remote=args.remote) if args.command=="hydrate" else persist(paths,message=args.message,branch=args.branch,remote=args.remote)
    print(out)

if __name__=="__main__":main()
