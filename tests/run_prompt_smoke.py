#!/usr/bin/env python3
import argparse, datetime as dt, json, os, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent

def load_dotenv(path):
    if not path.is_file(): return
    for raw in path.read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1)
        os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))

def call(api_key, model, system, prompt, effort):
    thinking = "disabled" if effort == "none" else "enabled"
    payload={"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":prompt}],"stream":False,"max_tokens":6000,"response_format":{"type":"json_object"},"reasoning_effort":effort,"thinking":{"type":thinking}}
    req=urllib.request.Request("https://api.deepseek.com/chat/completions",data=json.dumps(payload,ensure_ascii=False).encode(),method="POST",headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json","User-Agent":"research-deck-eval/0.1"})
    started=time.monotonic()
    with urllib.request.urlopen(req,timeout=300) as response:
        data=json.loads(response.read().decode())
    message=data["choices"][0]["message"]
    content=message.get("content") or ""
    if not content.strip():
        raise RuntimeError("empty final content; finish_reason="+str(data["choices"][0].get("finish_reason"))+" usage="+json.dumps(data.get("usage",{})))
    return json.loads(content),data.get("usage",{}),round(time.monotonic()-started,3)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--case',choices=['P1-clear','P1-ambiguous','P2-deep'])
    args=parser.parse_args()
    load_dotenv(PARENT/'.env')
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    if not key: raise SystemExit('DEEPSEEK_API_KEY missing in parent .env')
    system=(ROOT/'prompts/system.md').read_text()
    cases=[
      {"id":"P1-clear","stage":"P1","model":"deepseek-flash","effort":"none","input":{"topic":"CRISPR分子诊断的主要技术路线","tier":"fast","runtime_config":{"language":"zh-CN"}}},
      {"id":"P1-ambiguous","stage":"P1","model":"deepseek-flash","effort":"none","input":{"topic":"苹果","tier":"fast","runtime_config":{"language":"zh-CN"}}},
      {"id":"P2-deep","stage":"P2","model":"deepseek-v4-pro","effort":"high","input":{"intent":{"domain":"life_science","normalized_topic":"CAR-T用于实体瘤的技术路线比较","tier":"deep","need_clarification":False},"tier":"deep","available_sources":["PubMed","Europe PMC","Crossref","official"],"runtime_config":{"source_limit":19,"language":"zh-CN"}}}
    ]
    if args.case: cases=[case for case in cases if case['id']==args.case]
    stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    out=ROOT/'artifacts'/'prompt-smoke'/stamp
    out.mkdir(parents=True)
    results=[]
    totals={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
    for case in cases:
      stage=(ROOT/('prompts/P1-intent.md' if case['stage']=='P1' else 'prompts/P2-plan.md')).read_text()
      for run in range(1,args.repeats+1):
        parsed,usage,elapsed=call(key,case['model'],system,stage+'\n\n实际输入JSON：\n'+json.dumps(case['input'],ensure_ascii=False),case['effort'])
        for name in totals: totals[name]+=int(usage.get(name,0) or 0)
        item={"case_id":case['id'],"run":run,"stage":case['stage'],"model":case['model'],"effort":case['effort'],"elapsed_seconds":elapsed,"usage":usage,"output":parsed}
        results.append(item)
        (out/f"{case['id']}-run{run}.json").write_text(json.dumps(item,ensure_ascii=False,indent=2))
    p1_keys={'domain','normalized_topic','scope_hint','tier','assumptions','topic_breadth','direction_options','need_clarification','clarification_question','confirmation_text'}
    p2_keys={'research_scope','exclusions','questions','search_concepts','source_plan','selection_criteria','stop_conditions','report_outline','ppt_story_arc','risks'}
    def assess(r):
      output=r['output']; expected=p1_keys if r['stage']=='P1' else p2_keys
      contract_pass=set(output)==expected
      if r['case_id']=='P1-clear': semantic_pass=output.get('need_clarification') is False and output.get('clarification_question') is None
      elif r['case_id']=='P1-ambiguous': semantic_pass=output.get('need_clarification') is True and isinstance(output.get('clarification_question'),str) and bool(output['clarification_question'].strip())
      else:
        joined=json.dumps(output,ensure_ascii=False)
        semantic_pass=3<=len(output.get('questions',[]))<=6 and all(term in joined for term in ['比较','反证','冲突','适用'])
      return {"case_id":r['case_id'],"run":r['run'],"elapsed_seconds":r['elapsed_seconds'],"contract_pass":contract_pass,"semantic_pass":semantic_pass,"need_clarification":output.get('need_clarification'),"question_count":len(output.get('questions',[])),"output_keys":sorted(output)}
    summary={"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),"repeats":args.repeats,"calls":len(results),"usage":totals,"results":[assess(r) for r in results]}
    summary['all_pass']=all(r['contract_pass'] and r['semantic_pass'] for r in summary['results'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({"output":str(out),**summary},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
