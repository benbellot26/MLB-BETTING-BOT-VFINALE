from pathlib import Path

p=Path('bot.py')
s=p.read_text(encoding='utf-8')
marker='# ==================== V10.0.15 OFFICIAL SELECTOR LAB ====================='
if marker in s:
    print('V10.0.15 already patched')
    raise SystemExit(0)
needle='if __name__=="__main__":\n'
if needle not in s:
    raise SystemExit('main guard not found')
parts=[]
for name in ('tmp_v1015_layer1.txt','tmp_v1015_layer2.txt','tmp_v1015_layer3.txt'):
    parts.append((Path(__file__).parent/name).read_text(encoding='utf-8'))
layer='\n'.join(parts)+'\n'
s=s.replace(needle,layer+needle,1)
p.write_text(s,encoding='utf-8')
print('patched bot.py with V10.0.15')
