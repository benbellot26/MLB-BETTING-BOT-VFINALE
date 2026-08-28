from __future__ import annotations

"""Small dependency-free HTTP text client for V14 research data providers.

The caller can always inject a fetch function in tests/backfills. The default
client adds bounded retries for transient provider failures without swallowing
schema or permanent HTTP errors.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TRANSIENT_HTTP={408,425,429,500,502,503,504}


def http_text(url:str,params:dict[str,Any]|None=None,timeout:int|float=45,attempts:int=3)->str:
    target=str(url)
    if params:
        query=urllib.parse.urlencode(params,safe=",|[]")
        target+=("&" if "?" in target else "?")+query
    total=max(1,int(attempts)); last:Exception|None=None
    for attempt in range(total):
        try:
            req=urllib.request.Request(target,headers={"User-Agent":"Pulsar-V14-Research/1.0","Accept":"text/csv,text/plain,*/*"})
            with urllib.request.urlopen(req,timeout=float(timeout)) as response:
                return response.read().decode("utf-8","replace")
        except urllib.error.HTTPError as exc:
            last=exc
            if int(exc.code) not in TRANSIENT_HTTP or attempt+1>=total:raise
        except (urllib.error.URLError,TimeoutError) as exc:
            last=exc
            if attempt+1>=total:raise
        time.sleep(min(4.0,0.5*(2**attempt)))
    if last is not None:raise last
    raise RuntimeError("provider text fetch failed without exception")
