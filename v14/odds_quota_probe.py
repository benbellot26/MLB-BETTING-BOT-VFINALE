from __future__ import annotations

"""Zero-credit The Odds API quota probe.

The provider documents GET /v4/sports as not counting against usage quota while
returning x-requests-remaining, x-requests-used and x-requests-last. Pulsar uses
this endpoint only immediately before an otherwise-due paid opportunity, so a
fresh provider balance can veto the paid reservation without consuming credits.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .acquisition import DEFAULT_TIMEOUT, ODDS_QUOTA_STATE, write_odds_quota_state

SPORTS_URL="https://api.the-odds-api.com/v4/sports/"


def probe(*,api_key:str|None=None,state_path:Path|str=ODDS_QUOTA_STATE,timeout:int=DEFAULT_TIMEOUT)->dict[str,Any]:
    key=(api_key if api_key is not None else os.getenv("ODDS_API_KEY","")).strip()
    if not key:raise RuntimeError("ODDS_API_KEY absente")
    target=f"{SPORTS_URL}?{urlencode({'apiKey':key})}"
    request=Request(target,headers={"User-Agent":"Pulsar-V14-Quota-Probe","Accept":"application/json"})
    with urlopen(request,timeout=timeout) as response:
        body=response.read().decode("utf-8","replace")
        payload=json.loads(body) if body else []
        if not isinstance(payload,list):raise ValueError("The Odds API /sports payload must be a list")
        quota=write_odds_quota_state(response.headers,path=state_path)
    if not quota:raise RuntimeError("zero-credit provider probe returned no quota headers")
    return {"schema":"pulsar-v14-odds-quota-probe-v1","provider":"THE_ODDS_API","endpoint":"GET /v4/sports","provider_credit_cost":0,"sports_returned":len(payload),"quota":quota,"credentials_persisted":False}


def main()->None:
    parser=argparse.ArgumentParser(description="Refresh The Odds API quota headers using the zero-credit /sports endpoint")
    parser.add_argument("--state",default=str(ODDS_QUOTA_STATE));args=parser.parse_args();print(json.dumps(probe(state_path=args.state),ensure_ascii=False,sort_keys=True))


if __name__=="__main__":main()
