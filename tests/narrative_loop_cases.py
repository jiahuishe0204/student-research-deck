"""Predeclared synthetic controls and real regression pages; not research claims."""
import copy
from canonical_surface import prepare_case
from tests.run_narrative_bound_pilot import cases as real_cases

def synthetic(pid,title,question,facts,bridges,figure=None):
    canonical={f'C{i}':{'text':fact,'evidence_ids':[f'E{i}']} for i,fact in enumerate(facts,1)}
    case={'page_id':pid,'topic_key':title,'canonical':canonical,'purpose':question,
          'plan':{'central_question':question,'ppt_story_arc':['定义问题','观察结果','解释边界','后续验证']},
          'previous_title':'研究设计','next_title':'验证与展望','fixture_kind':'synthetic_not_real_research',
          'source_figures':[] if figure is None else [figure],
          'evidence_sources':{f'E{i}':'S1' for i in range(1,len(facts)+1)}}
    page={'page_id':pid,'topic_key':title,'segments':[{'kind':'bridge','value':bridges[0]}]+
          [{'kind':'claim','value':cid} for cid in canonical]+[{'kind':'bridge','value':bridges[1]}], 'figure_choices':[]}
    return case,page

def development():
    result=real_cases()
    for c in result:
        c['evidence_sources']={e:e[4:].rsplit('::',1)[0] for v in c['canonical'].values() for e in v['evidence_ids']}
    education,_=synthetic('EDU','学习时长与成绩','观察到的相关性能否解释为学习时长的因果作用？',
        ['在这个假设性横断面样本中，学习时长与考试成绩呈正相关。',
         '该样本没有随机分配学习时长，家庭支持等混杂因素未得到控制，不能据此推断增加学习时长会提高成绩。'],
        ['这一观察能否支持因果解释？','需要区分观察到的关联和需要另行验证的干预效果。'])
    battery,_=synthetic('MAT','循环保持率与寿命','特定测试下的保持率能否代表通用寿命优势？',
        ['在假设性试验的25°C、1C倍率条件下，材料A在100次循环后的容量保持率为90%，材料B为85%。',
         '这组数据仅描述所测条件下的100次循环结果，未测其他温度或完整失效寿命，不能据此推断材料A在所有条件下寿命更长。'],
        ['这组比较回答的是哪一种性能问题？','这里可以讨论特定条件下的保持率，完整寿命则需要另行验证。'],
        {'figure_id':'F1','source_id':'S1','caption':'Figure 1. (a) 25°C、1C下A和B的100次循环容量保持率；(b) 材料形貌。','reuse_status':'unknown'})
    return result+[education,battery]

def controls():
    ed,ep=synthetic('CTRL-E','观察与因果','关联是否等于因果？',
        ['在假设性横断面样本中，学习时长与考试成绩呈正相关，但不能据此推断因果。'],
        ['这一关联能否解释为因果作用？','因此，不能据此断言增加学习时长会提高成绩。'])
    mat,mp=synthetic('CTRL-M','保持率比较','测试结果的适用范围是什么？',
        ['假设性试验中，在25°C、1C下测试100次循环，A容量保持率90%、B为85%；结果不能外推至全部温度或失效寿命。'],
        ['这一结果回答的是特定测试下的比较问题。','后续应分别评估测试条件之外的表现。'],
        {'figure_id':'F1','source_id':'S1','caption':'Figure 1. (a) 25°C、1C下100次循环容量保持率；(b) 材料显微形貌。','reuse_status':'unknown'})
    mp['figure_choices']=[{'figure_id':'F1','claim_ids':['C1'],'panel':'Figure 1a','reason':'展示所测条件下100次循环的容量保持率。'}]
    bad_e=copy.deepcopy(ep)
    bad_e['segments'] += [{'kind':'bridge','value':'因此已经证实延长学习时间会直接提高成绩。'},
                          {'kind':'bridge','value':'而且这一干预对所有年龄人群都有效。'}]
    bad_m=copy.deepcopy(mp)
    bad_m['segments'].append({'kind':'bridge','value':'由此可见A在任何温度下的失效寿命都比B更长。'})
    bad_m['figure_choices'][0].update(panel='Figure 1b',reason='分图b直接展示100次循环的容量保持率比较。')
    group,gp=synthetic('CTRL-G','比较条件归属','两组是否处于可直接比较的状态？',
        ['固定12 mA、n=1条件下，Pt已达到电荷注入极限而凝胶未达到，因此不能直接比较电荷注入效率。'],
        ['两组的测量条件是否支持直接比较？','Pt已达到极限，凝胶未达到，不能把这一差异当作效率优势。'])
    bad_g=copy.deepcopy(gp)
    bad_g['segments'][2]['value']='该测试未达到电荷注入极限，因此两组均处于相同状态。'
    numeric,np=synthetic('CTRL-N','比例一致性','这项比例能否用于定量结论？',
        ['假设性记录声称38.7%（334/686）为阳性。'],
        ['这项记录能否直接用于定量比较？','该记录中百分比和计数存在矛盾，因此暂不采用这一比例作定量结论。'])
    numeric=prepare_case(numeric)
    bad_n=copy.deepcopy(np)
    bad_n['segments'][2]['value']='因此可以确认真实阳性率就是38.7%。'
    uncertain,up=synthetic('CTRL-U','作用归属','效应能否归因于工具？',
        ['假设性记录中观察到行为效应，未证明由电极本身直接引起。'],
        ['这项观察能否支持归因？','目前不能确认电极本身是否直接产生该效应。'])
    bad_u=copy.deepcopy(up)
    bad_u['segments'][2]['value']='因此该效应并非由电极本身直接引起。'
    bad_method=copy.deepcopy(gp)
    bad_method['segments'][2]['value']='要比较效率，必须让两组都达到电荷注入极限。'
    good_method=copy.deepcopy(gp)
    good_method['segments'][2]['value']='该比较仍需在可比条件下进一步验证。'
    return [('positive-no-figure',ed,ep,[]),('positive-matched-figure',mat,mp,[]),
            ('negative-causality-generalization',ed,bad_e,['segments/3','segments/4']),
            ('negative-lifetime-wrong-panel',mat,bad_m,['segments/3','figure_choices/0']),
            ('positive-group-conditions',group,gp,[]),('negative-group-conditions',group,bad_g,['segments/2']),
            ('positive-source-disclosure',numeric,np,[]),('negative-unsupported-rate',numeric,bad_n,['segments/2']),
            ('positive-uncertainty',uncertain,up,[]),('negative-uncertainty-reversal',uncertain,bad_u,['segments/2']),
            ('negative-unsupported-method',group,bad_method,['segments/2']),
            ('positive-generic-method',group,good_method,[])]
