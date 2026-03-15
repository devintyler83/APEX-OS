import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from draftos.apex.prompts import build_system_prompt, POSITION_PAA_GATES, _normalize_position_for_gate
prompt = build_system_prompt()

print("=== WEIGHT TABLE VERIFICATION ===")
weight_blocks = re.findall(r'BASE WEIGHT TABLE:\n(.*?)(?:\n\n|\nARCHETYPE|\nPAA|\nSOS|\nSAA)', prompt, re.DOTALL)
print(f'Weight table blocks found: {len(weight_blocks)}')
all_ok = True
for i, block in enumerate(weight_blocks):
    percentages = re.findall(r'(\d+)%', block)
    total = sum(int(p) for p in percentages)
    ok = total == 100
    print(f'  Block {i+1}: {percentages} = {total}% {"OK" if ok else "MISMATCH"}')
    if not ok:
        all_ok = False

# IDL tables
idl_blocks = re.findall(r'TABLE [AB] — [^\n]+:\n(.*?)(?:\n\n|ARCHETYPES)', prompt, re.DOTALL)
print(f'IDL table blocks found: {len(idl_blocks)}')
for i, block in enumerate(idl_blocks):
    percentages = re.findall(r'(\d+)%', block)
    total = sum(int(p) for p in percentages)
    ok = total == 100
    print(f'  IDL Table {i+1}: {percentages} = {total}% {"OK" if ok else "MISMATCH"}')
    if not ok:
        all_ok = False

print()
print(f'All weight tables 100%: {all_ok}')

print()
print("=== SECTION B POSITION COUNT ===")
pos_headers = re.findall(r'POSITION: ([A-Z/\s]+) \(PVC', prompt)
print(f'Position sections: {len(pos_headers)}')
for p in pos_headers:
    print(f'  {p.strip()}')
fallback = 'FALLBACK' in prompt
print(f'FALLBACK section: {fallback}')

print()
print("=== GEN- REFERENCE CHECK ===")
gen_matches = re.findall(r'GEN-\d+', prompt)
print(f'GEN- archetype references (expect 0): {len(gen_matches)}')

print()
print("=== POSITION_PAA_GATES KEYS ===")
for k in sorted(POSITION_PAA_GATES.keys()):
    print(f'  {k}')

print()
print("=== NORMALIZE POSITION TEST ===")
test_cases = [('ILB', 'ILB'), ('OLB', 'OLB'), ('LB', 'ILB'), ('DT', 'DT'),
              ('IDL', 'DT'), ('CB', 'CB'), ('S', 'S'), ('C', 'C'),
              ('OG', 'OG'), ('OT', 'OT'), ('EDGE', 'EDGE'), ('QB', 'QB')]
for pos, expected in test_cases:
    result = _normalize_position_for_gate(pos)
    ok = result == expected
    print(f'  {pos} -> {result} {"OK" if ok else f"EXPECTED {expected}"}')
