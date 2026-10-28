'cognitivebreak: auxiliary compilation of the bounded source sketch.'
from typing import Any
from models import bounded_openrouter_chat, load_project_env
import source_brief

def compile_source(goal: str, model: str, timeout: int, max_tokens: int) -> dict[str, Any]:
    load_project_env()
    served=model.removeprefix('api:'); steps=[]
    for attempt in range(2):
        prompt=source_brief.prompt(goal,"a field sketch for a reverse-causal narrative")
        step={"model":served,"prompt":prompt}
        try:
            reply=bounded_openrouter_chat(served,[{"role":"user","content":prompt}],timeout,max_tokens,0.0)
            step['output']=str(reply['content']); draft=source_brief.parse(step['output'])
            if draft is not None and source_brief._defensive(draft):
                step['gate']={'decision':'defensive_frame'};steps.append(step);draft=None
                continue
            if draft is not None:
                overlap = source_brief.goal_overlap(draft['objective'], goal)
            if draft is not None and overlap < 2:
                step['gate']={'decision':'objective_goal_mismatch'};steps.append(step);draft=None
                continue
        except Exception as exc:
            step['error']=str(exc)[:300];draft=None
        step['gate']={'decision':'accepted' if draft else 'invalid_source_schema'};steps.append(step)
        if draft is not None:
            return {'source':source_brief.render(draft),'source_compiled':True,'steps':steps}
    return {'source':source_brief.render(source_brief.fallback(goal)),'source_compiled':False,'steps':steps}
