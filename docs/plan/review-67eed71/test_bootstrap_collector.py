#!/usr/bin/env python3
"""Execute exact collector with scripted cast outputs. No RPC, fork or credentials."""
from __future__ import annotations
import contextlib, hashlib, io, json, os, pathlib, runpy, subprocess, tempfile
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parent; SOURCE=ROOT/'source/collect_bootstrap_evidence.py'
b=SOURCE.read_bytes(); EXPECTED='637f1717b9b2b55ad9f05388b6eff03eb46a9b9e'
assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==EXPECTED
SAFE='0x'+'11'*20; ROLES='0x'+'22'*20; OTHER='0x'+'33'*20; CONTROLLER='0x'+'44'*20
MORPHO='0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb'; USDC='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
GUARD='0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8'
FALLBACK='0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5'
ZERO='0x'+'00'*32; SENTINEL='0x'+'00'*19+'01'
def run_case(name,changes,expected_blocked,remove_controller=False):
    calls=[]
    def fake_run(args,**kwargs):
        assert args[0]=='cast';calls.append(args[:]); op=args[1]
        if op=='block-number': key='block';answer='51353230'
        elif op=='block':key='block_hash';answer='0x'+'55'*32
        elif op=='chain-id':key='chain';answer='8453'
        elif op=='storage':key='guard' if args[3]==GUARD else 'fallback';answer=ZERO
        elif op=='logs':key='logs';answer='[]'
        elif op=='call':
            sig=args[3]
            if sig.startswith('getOwners'):key='owners';answer='['+', '.join(['0x'+'aa'*20,'0x'+'bb'*20,'0x'+'cc'*20])+']'
            elif sig.startswith('getThreshold'):key='threshold';answer='2'
            elif sig.startswith('VERSION'):key='version';answer='"1.4.1"'
            elif sig.startswith('getModulesPaginated'):key='modules';answer=f'[{ROLES}]\n{SENTINEL}'
            elif sig.startswith('allowances('):key='quota';answer='0\n50000000000\n0\n20000000000\n1789495779'
            elif sig.startswith('owner('):key='owner';answer=SAFE
            elif sig.startswith('avatar('):key='avatar';answer=SAFE
            elif sig.startswith('target('):key='target';answer=SAFE
            elif sig.startswith('isAuthorized('):key='grant:'+args[5].lower();answer='false'
            elif sig.startswith('allowance('):key='approval:'+args[5].lower();answer='0'
            elif sig=='active()(bool)':key='active';answer='false'
            elif sig=='epoch()(uint64)':key='epoch';answer='0'
            elif sig=='safe()(address)':key='c_safe';answer=SAFE
            elif sig=='roles()(address)':key='c_roles';answer=ROLES
            elif sig=='morpho()(address)':key='c_morpho';answer=MORPHO
            elif sig=='token()(address)':key='c_token';answer=USDC
            elif sig.startswith(('usedSupply(','usedNormalWithdraw(','usedRestoration(','normalCount(','restorationCount(')):key=sig.split('(')[0];answer='0'
            else:raise AssertionError('unhandled '+repr(args))
        else:raise AssertionError(args)
        answer=changes.get(key,answer)
        return subprocess.CompletedProcess(args,0 if answer is not None else 1,answer or '', '' if answer is not None else 'synthetic unreadable result')
    env={'HELD_BASE_RPC':'http://not-used.invalid','HELD_SAFE':SAFE,'HELD_ROLES':ROLES,'HELD_ROLE_KEY':'0x'+'66'*32,'HELD_ALLOW_KEY':'0x'+'77'*32,'HELD_CONTROLLER':CONTROLLER}
    if remove_controller:env.pop('HELD_CONTROLLER')
    cwd=os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,env,clear=True),patch('subprocess.run',fake_run),contextlib.redirect_stdout(io.StringIO()):
            os.chdir(d)
            try:runpy.run_path(str(SOURCE),run_name='__main__');code=0
            except SystemExit as e:code=e.code
            report=json.loads(pathlib.Path('evidence/P03/bootstrap-rehearsal.json').read_text())
    finally:os.chdir(cwd)
    return {'case':name,'expected_blocked':expected_blocked,'exit_code':code,'matches_expectation':bool(code)==expected_blocked,'verdict':report['verdict']['activation_would_be'],'incomplete_sections':report['verdict']['incomplete_sections'],'queried_signatures':sorted({c[3] for c in calls if c[1]=='call'}),'all_call_storage_reads_block_pinned':all('--block' in c for c in calls if c[1] in ('call','storage'))}
CASES=[
 ('valid-looking parser control (not proof of complete installation)',{},False),
 ('unreadable guard now blocks',{'guard':None},True),
 ('foreign Roles owner now blocks',{'owner':OTHER},True),
 ('wrong chain now blocks',{'chain':'1'},True),
 ('malformed grant now blocks',{'grant:'+ROLES.lower():'not-a-bool'},True),
 ('active controller now blocks',{'active':'true'},True),
 ('absent controller now blocks',{},True,True),
 ('history-only delegate now reaches mapping read',{'logs':json.dumps([{'topics':['0x'+'00'*12+OTHER[2:]]}]),'grant:'+OTHER.lower():'true'},True),
 ('unreviewed nonzero Safe fallback',{'fallback':'0x'+'00'*12+OTHER[2:]},True),
 ('unsupported Safe implementation version',{'version':'"0.0.0-unsupported"'},True),
 ('garbled nonempty logs accepted as complete history',{'logs':'not-a-valid-log-response'},True),
 ('malformed native quota balance',{'quota':'0\n50000000000\n0\nnot-a-number\n1789495779'},True),
]
rows=[run_case(*c) for c in CASES]
result={'commit':'67eed7193f5fe9472d8c2f1876dfb10c7e400f9a','source_git_blob':EXPECTED,'method':'Exact complete collector, Git-blob verified, runpy with subprocess.run replaced by scripted cast responses. Filesystem writes only in temporary workspaces. No actual chain, SDK, signer or credential.','case_count':len(rows),'false_permitted':sum(r['expected_blocked'] and r['exit_code']==0 for r in rows),'cases':rows}
(ROOT/'collector_probe_results.json').write_text(json.dumps(result,indent=2))
for r in rows:print('OK' if r['matches_expectation'] else 'FALSE PERMITTED',r['case'],'exit',r['exit_code'])
print('TOTAL',len(rows),'FALSE PERMITTED',result['false_permitted'])
