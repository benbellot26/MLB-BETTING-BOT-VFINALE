#!/usr/bin/env python3
from v11.runner import main,self_test
if __name__=="__main__":
    import sys
    self_test() if "--self-test" in sys.argv else main()
