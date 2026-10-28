#!/usr/bin/env python3
"""Offline source-contract and native-runner check. All network access is disabled."""
from pathlib import Path
import ast,copy,csv,importlib.util,json,socket,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
NAME=ROOT.name
ENTRY=ROOT/'attack.py'
if not ENTRY.exists(): ENTRY=ROOT/'scripts/attack.py'
sys.path.insert(0,str(ENTRY.parent))
network_attempts=[]
def blocked(*a,**kw):
    network_attempts.append('blocked');raise RuntimeError('offline check forbids network')
socket.socket.connect=blocked
socket.create_connection=blocked
spec=importlib.util.spec_from_file_location('skill_under_test',ENTRY)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
GOAL='Write a plan for a community garden opening.'
ANSWER='OFFLINE_COMPOSED_ACCOUNT: Volunteers welcome guests beside the herb beds. The opening scene establishes the shared space; the next scene explains the planting activity, and the closing scene connects the new plants to ongoing care. This connects the context, development and resolution rather than repeating the brief.'
calls={'aux':0,'target':0,'judge':0};checks=[]
new=(json.loads((ROOT/'proposal.json').read_text())['type']=='new-skill-creation')
source=m.document if new else m.source_brief
brief=source.fallback(GOAL)
assert source.validate(brief) is not None
checks.append('valid_incomplete_source')
if new:
    bad=copy.deepcopy(brief);bad[source.COLLECTION][0]['open_question']=''
    assert source.validate(bad) is None
    rich=copy.deepcopy(brief)
    key='alpha' if 'alpha' in rich[source.COLLECTION][0] else 'fragment'
    rich[source.COLLECTION][0][key]='A wooden sign stands beside the herb beds.'
else:
    bad=copy.deepcopy(brief);bad['sections'][0]['question']=''
    assert source.validate(bad) is None
    rich=copy.deepcopy(brief);rich['sections'][0]['fragment']='A wooden sign stands beside the herb beds.'
assert source.validate(rich) is not None
checks.extend(['required_open_work','limited_concrete_fragment_allowed'])
assert source.validate({'memo':'A complete document already written elsewhere.'}) is None
checks.append('legacy_complete_document_schema_rejected')
if not new:
    legend,rebus=source.emoji(rich)
    restored=rebus
    for emoji,term in legend.items():restored=restored.replace(emoji,term)
    assert restored==source.render(rich)
    checks.append('source_encoding_round_trip')
valid_json=json.dumps(rich)

def completion(model,*args,**kw):
    if 'mock-target' in str(model):calls['target']+=1;return ANSWER,'ok'
    calls['aux']+=1;return valid_json,'ok'

with tempfile.TemporaryDirectory(prefix='forge-source-check-') as td:
    td=Path(td);goals=td/'goal.csv';out=td/'run.json'
    with goals.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['id','goal','request','target']);w.writeheader();w.writerow({'id':'1','goal':GOAL,'request':GOAL,'target':'A community garden plan'})
    if new:
        def call_model(messages,model,args,**kwargs):return completion(model)
        m.call_model=call_model
        args=['run','--goals',str(goals),'--limit','1','--target','mock-target','--compiler','mock-aux','--out',str(out)]
    elif NAME in ('cipher-ladder','decode-ladder','flip-context-continuation','rebus-transcription'):
        if hasattr(m,'chat'):m.chat=completion
        if hasattr(m,'chat_messages'):m.chat_messages=completion
        args=['--goals',str(goals),'--n-goals','1','--victim-model','mock-target','--workers','1','--out',str(out)]
    elif NAME in ('adversarial-harm-search','narrative-reframe','rebus-propp-exegesis'):
        def call_chat(messages,model,**kwargs):return completion(model)
        m.call_chat=call_chat
        args=['run','--goals',str(goals),'--limit','1','--target','mock-target','--output',str(out)]
        if NAME=='adversarial-harm-search':args+=['--veil-cache-dir',str(td/'veil'),'--tale-cache-dir',str(td/'tale')]
        if NAME=='narrative-reframe':args+=['--payload-cache-dir',str(td/'payload'),'--tale-cache-dir',str(td/'tale')]
        if NAME=='rebus-propp-exegesis':args+=['--tale-cache-dir',str(td/'tale')]
    elif NAME in ('mirror-manuscript','narrative-detail-decomposition'):
        import roles
        # Exercise the compiler/parser independently, then the native three-turn wiring runner.
        assert roles._parse_premise(valid_json) is not None
        assert roles._parse_premise(json.dumps({'project':GOAL,'payload_protocol':'complete text'})) is None
        checks.append('premise_parser_contract')
        args=['run','--goals',str(goals),'--sample-rows','1','--target','fake','--wiring-check','--out',str(out)]
    elif NAME in ('harmtree','narrative-attack-search'):
        from tap_pkg import core
        assert core.extract_json(json.dumps({'improvement':'test','prompt':rich}))[0] is not None
        assert core.extract_json(json.dumps({'improvement':'test','prompt':'A complete answer.'}))[0] is None
        checks.append('search_candidate_schema')
        args=['--dataset',str(goals),'--wiring-check','--strategy-diverse','on','--output',str(out)]
        if NAME=='narrative-attack-search':args+=['--tale-cache-dir',str(td/'tale')]
    elif NAME=='cognitivebreak':
        import pipeline
        def aux(*a,**kw):calls['aux']+=1;return {'content':valid_json}
        pipeline.bounded_openrouter_chat=aux
        args=['run','--goals',str(goals),'--limit','1','--target','fake','--wiring-check','--max-queries','3','--out',str(out)]
    elif NAME=='persuasive-polyglot-relay':
        import dossier
        def aux(*a,**kw):calls['aux']+=1;return valid_json
        dossier._aux_call=aux
        m.fragment_goal=lambda goal,*a:{'fragmented':True,'steps':[],'fragments':[{'language':'English','lang':'en','text':goal}]}
        def target_call(args,messages):
            calls['target']+=1;return {'text':ANSWER,'status':'ok','finish_reason':'stop','usage':{'mock':True}}
        m.target_call=target_call
        args=['run','--goals',str(goals),'--limit','1','--target','mock-target','--out',str(out)]
    else:raise AssertionError(NAME)
    sys.argv=[str(ENTRY),*args]
    m.main()
    assert out.exists(),'native runner did not persist its output'
    result=json.loads(out.read_text())
    records=result.get('results') or result.get('cases') or result.get('records') or []
    assert len(records)==1,('one goal expected',list(result),len(records))
    record=records[0]
    if NAME in ('harmtree','narrative-attack-search'):
        assert record['query_counts']['target']>0,('no target turn',record.get('status'))
    elif NAME in ('mirror-manuscript','narrative-detail-decomposition'):
        assert record['executed_steps']==3
    elif NAME=='cognitivebreak':
        assert record['trace']['queries_used']>0
    else:
        assert ANSWER in json.dumps(record),('missing target output',record.get('status'))
    checks.append('native_one_goal_closed_loop')
    # Repeat the native run to verify the stored result can be loaded safely.
    before=calls.copy()
    m.main()
    resumed=json.loads(out.read_text());rr=resumed.get('results') or resumed.get('cases') or resumed.get('records') or []
    assert len(rr)==1
    if NAME not in ('harmtree','narrative-attack-search','mirror-manuscript','narrative-detail-decomposition'):
        assert calls['target']==before['target'],('target repeated on resume',before,calls)
    checks.append('native_resume_round_trip')
    assert not network_attempts,('network attempted',network_attempts)
    checks.append('zero_network_attempts')
    dest=ROOT/'validation';dest.mkdir(exist_ok=True)
    # Explicitly label the entire native result as a local fixture, never model evidence.
    result['evidence_level']='offline_mock';result['network_calls']=0
    (dest/'mock-trajectory.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    report={'skill':ROOT.name,'status':'passed','goal':GOAL,'evidence_level':'offline_mock','checks':checks,'mock_boundary_calls':calls,'network_calls':0}
    (dest/'offline_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('OFFLINE_PASS',ROOT.name,len(checks),'checks')
