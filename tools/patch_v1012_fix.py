from pathlib import Path
p=Path('bot.py')
s=p.read_text(encoding='utf-8')
old='_V1011_SELF_TEST_012=v10_self_test\n\nVERSION="10.0.12"'
new='_V1011_SELF_TEST_012=v10_self_test\n_V1011_CANDIDATE_012=v1011_candidate\n\nVERSION="10.0.12"'
if old not in s and '_V1011_CANDIDATE_012=v1011_candidate' not in s:
    raise SystemExit('candidate capture anchor not found')
s=s.replace(old,new,1)
old2='def v10_self_test():\n    global VERSION\n    current=VERSION;VERSION="10.0.11"\n    try:_V1011_SELF_TEST_012()\n    finally:VERSION=current'
new2='def v10_self_test():\n    global VERSION,v1011_candidate\n    current=VERSION;current_candidate=v1011_candidate;VERSION="10.0.11";v1011_candidate=_V1011_CANDIDATE_012\n    try:_V1011_SELF_TEST_012()\n    finally:VERSION=current;v1011_candidate=current_candidate'
if old2 not in s:
    raise SystemExit('self-test wrapper anchor not found')
s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8')
print('Applied V10.0.12 compatibility fix')
