#!/usr/bin/env python3
"""Exact committed adapter; synthetic machine + SQLite harness. No SDK, RPC or signer."""
from __future__ import annotations
import contextlib, hashlib, importlib.util, json, pathlib, sqlite3, sys, tempfile
from types import SimpleNamespace
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parent
SOURCE=ROOT/'source/native_result.py'
b=SOURCE.read_bytes(); expected='6b3299a0de956e076b59183c9a570105a2a34310'
assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==expected
spec=importlib.util.spec_from_file_location('held_review_native',SOURCE)
n=importlib.util.module_from_spec(spec); sys.modules[spec.name]=n; spec.loader.exec_module(n)
class SQLiteHarness:
    def __init__(self,path):
        self.path=path
        self._db=sqlite3.connect(path,isolation_level=None);self._db.row_factory=sqlite3.Row
        self._db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS operations(operation_id TEXT PRIMARY KEY,state TEXT,payload_hash TEXT);')
    @contextlib.contextmanager
    def transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try: yield self._db;self._db.execute('COMMIT')
        except Exception: self._db.execute('ROLLBACK');raise
    def set_state(self,oid,state): self._db.execute('INSERT OR REPLACE INTO operations VALUES(?,?,?)',(oid,state,'0x'+'11'*32))
    def get(self,oid):
        r=self._db.execute('SELECT * FROM operations WHERE operation_id=?',(oid,)).fetchone()
        return SimpleNamespace(state=SimpleNamespace(value=r['state'])) if r else None
    def close(self): self._db.close()
class Machine:
    """Controlled model of native step; explicitly NOT Almanak."""
    def __init__(self,intent='decision-A',state='VALIDATING_SUPPLY'):
        self.intent=SimpleNamespace(intent_id=intent,intent_type=SimpleNamespace(value='SUPPLY'))
        self.state=state;self.receipt=None;self.step_count=0
    def set_receipt(self,r): self.receipt=r
    def step(self):
        self.step_count+=1
        if self.receipt is not None:self.state='COMPLETED' if self.receipt.success else 'SADFLOW_SUPPLY'
        c=self.state=='COMPLETED'
        return SimpleNamespace(needs_execution=not c,is_complete=c,success=c,error=None)
    def to_dict(self):return {'intent_id':self.intent.intent_id,'intent_type':'SUPPLY','state':self.state}
OID='0x'+'11'*32; RH='0x'+'99'*32
PAYLOAD=json.dumps({'success':True,'tx_hash':'0x'+'44'*32,'block_number':123})
rows=[]
def save(j,state='COMPLETED',intent='decision-A',ack=True):
    with j.transaction() as c:
        c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(n.NATIVE_STATE_KEY.format(operation_id=OID),json.dumps({'state':state,'intent_id':intent,'held_bound_decision':{'intent_id':intent,'intent_type':'SUPPLY'}})))
        if ack:c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(n.NATIVE_ACK_KEY.format(operation_id=OID),state))
def read_decision(r):
    try:return {'needs_execution':r.needs_execution(),'refused':False}
    except (n.NativeRecoveryBlocked,n.NativeStateNotAuthoritative) as e:return {'refused':True,'error':str(e)}
def run():
    with tempfile.TemporaryDirectory() as d,patch.object(n.NativeReceipt,'to_native',lambda self:self):
        def fresh(name):return SQLiteHarness(str(pathlib.Path(d)/(name+'.sqlite')))
        j=fresh('binding');n.bind_native_decision(j,OID,'decision-A','SUPPLY');n.bind_native_decision(j,OID,'decision-A','SUPPLY')
        rows.append({'case':'identical binding reopens','fixed_control':True,'stored':n.bound_native_decision(j,OID)})
        try:n.bind_native_decision(j,OID,'decision-B','WITHDRAW');refused=False
        except n.NativeDecisionConflict:refused=True
        rows.append({'case':'changed decision/type rejected','fixed_control':True,'refused':refused})
        c=n.NativeStateMachineConsumer(Machine('decision-B'))
        try:
            with j.transaction() as conn:c.apply(conn,OID,RH,PAYLOAD)
            refused=False
        except n.NativeDecisionConflict:refused=True
        rows.append({'case':'wrong-machine application blocked before mutation','fixed_control':True,'refused':refused,'machine_steps':c.machine.step_count});j.close()
        for state in ('CONFIRMED','UNKNOWN','DISPATCHED'):
            j=fresh(state);j.set_state(OID,state);n.bind_native_decision(j,OID,'decision-A','SUPPLY');built=[]
            r=n.restore(j,OID,build_machine=lambda:built.append(1) or Machine())
            rows.append({'case':state+' without native snapshot','fixed_control':True,'machines_built':len(built),**read_decision(r)});j.close()
        j=fresh('good');j.set_state(OID,'CONFIRMED');n.bind_native_decision(j,OID,'decision-A','SUPPLY');c=n.NativeStateMachineConsumer(Machine())
        with j.transaction() as conn:c.apply(conn,OID,RH,PAYLOAD)
        verified=c.verify_committed(j,OID);j.close();j=SQLiteHarness(str(pathlib.Path(d)/'good.sqlite'));built=[]
        r=n.restore(j,OID,build_machine=lambda:built.append(1) or Machine())
        rows.append({'case':'matching committed checkpoint reopens','fixed_control':True,'verified':verified,'complete':r.complete,'machines_built':len(built),**read_decision(r)});j.close()
        j=fresh('rollback');j.set_state(OID,'CONFIRMED');n.bind_native_decision(j,OID,'decision-A','SUPPLY');c=n.NativeStateMachineConsumer(Machine());seen=None
        try:
            with j.transaction() as conn:
                c.apply(conn,OID,RH,PAYLOAD)
                seen=c.verify_committed(j,OID)
                raise RuntimeError('fail after mutation, before commit')
        except RuntimeError:pass
        rows.append({'case':'separate-connection verification cannot see uncommitted snapshot','fixed_control':True,'verified_before_commit':seen,'snapshot_after_rollback':n.native_state_after(j,OID)})
        rows.append({'case':'public needs_execution still consults dirty uncommitted machine','remaining_finding':True,'authoritative':c.authoritative,'native_state':c.state,**read_decision(c),'expected':'refuse reuse pending restoration'});j.close()
        j=fresh('wrong-checkpoint');j.set_state(OID,'CONFIRMED');n.bind_native_decision(j,OID,'decision-A','SUPPLY');save(j,intent='decision-B');r=n.restore(j,OID)
        rows.append({'case':'restore accepts snapshot B under binding A','remaining_finding':True,'manufactured_inconsistent_checkpoint':True,'bound_intent':r.intent_id,'snapshot_intent':n.native_state_after(j,OID)['intent_id'],'complete':r.complete,'inconsistent':r.inconsistent,**read_decision(r),'expected':'report mismatch and block'});j.close()
        j=fresh('missing-operation');n.bind_native_decision(j,OID,'decision-A','SUPPLY');built=[]
        r=n.restore(j,OID,build_machine=lambda:built.append(1) or Machine())
        rows.append({'case':'restore builds work with no durable operation','remaining_finding':True,'manufactured_missing_history':True,'operation_state':r.operation_state,'machines_built':len(built),**read_decision(r),'expected':'fail closed on missing operation/recovery evidence'});j.close()
        j=fresh('terminal-unacked');j.set_state(OID,'CONFIRMED');n.bind_native_decision(j,OID,'decision-A','SUPPLY');save(j,ack=False);r=n.restore(j,OID)
        rows.append({'case':'terminal snapshot without acknowledgement blocked','fixed_control':True,'complete':r.complete,**read_decision(r)});j.close()
    result={'commit':'67eed7193f5fe9472d8c2f1876dfb10c7e400f9a','source_git_blob':expected,'method':'Exact complete adapter source, Git-blob verified. SQLiteHarness and Machine are synthetic dependencies; actual sqlite transactions and close/reopen, no real Held Journal or SDK. No network/signing/transactions.','case_count':len(rows),'cases':rows}
    (ROOT/'native_probe_results.json').write_text(json.dumps(result,indent=2))
    for r in rows:print(r['case'],json.dumps({k:v for k,v in r.items() if k not in ('case','expected')}))
if __name__=='__main__':run()
