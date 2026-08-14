#!/usr/bin/env python3
from v11.train import write_candidate

if __name__ == "__main__":
    import json
    candidate = write_candidate()
    print(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True))
