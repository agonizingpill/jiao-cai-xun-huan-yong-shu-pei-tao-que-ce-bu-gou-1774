import hashlib,json,itertools
import numpy as np

def apriori(baskets,min_support=.15,min_confidence=.6):
    n=len(baskets);items=sorted(set().union(*baskets));counts={};previous=set()
    for k in range(1,4):
        current=set()
        for combo in itertools.combinations(items,k):
            key=frozenset(combo)
            if k>1 and not all(frozenset(sub)in previous for sub in itertools.combinations(combo,k-1)):continue
            count=sum(key<=basket for basket in baskets)
            if count/n>=min_support:counts[key]=count;current.add(key)
        previous=current
        if not current:break
    rules=[]
    for itemset,count in counts.items():
        if len(itemset)<2:continue
        for rhs in sorted(itemset):
            lhs=itemset-{rhs};confidence=count/counts[lhs];lift=confidence/(counts[frozenset([rhs])]/n)
            if confidence>=min_confidence and lift>1:rules.append({'if_subjects':sorted(lhs),'then_subject':rhs,'support':round(count/n,4),'confidence':round(confidence,4),'lift':round(lift,4)})
    return sorted(rules,key=lambda r:(-r['lift'],-r['confidence'],r['then_subject']))

def _conflict_map(pairs):
    graph={}
    for a,b in pairs:
        graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
    return graph

def _conflicts_with(subject,chosen,graph):
    return sorted(graph.get(subject,set())&set(chosen))

def _best_coexist_group(candidates,graph):
    # 先尽量多留能一起开的科目（最大独立集）；同容量再比关联强弱（lift 总和，次比置信度）。
    # 候选规模来自最多三项的Apriori规则，数量很小，枚举可行子集即可。
    best=None
    for size in range(len(candidates),0,-1):
        for combo in itertools.combinations(candidates,size):
            names={c['then_subject']for c in combo}
            if any(_conflicts_with(c['then_subject'],names-{c['then_subject']},graph)for c in combo):continue
            score=(-sum(c['lift']for c in combo),-sum(c['confidence']for c in combo),tuple(sorted(names)))
            if best is None or score<best[0]:best=(score,list(combo))
        if best:return best[1]
    return []

def apply_mutex(rules,current_subjects,pairs):
    # current_subjects：已排/已见科目；pairs：本次分析所用互斥关系快照
    graph=_conflict_map(pairs);current=set(current_subjects);conflicts=[];eligible=[]
    for r in rules:
        candidate=r['then_subject']
        if candidate in current:continue
        blocked=_conflicts_with(candidate,current,graph)
        if blocked:
            conflicts.append({'subject':candidate,'rule':r,'reason':'与已登记科目互斥','blocked_by':blocked})
        else:eligible.append(r)
    kept=_best_coexist_group(eligible,graph)
    kept_names={r['then_subject']for r in kept}
    for r in eligible:
        if r['then_subject']not in kept_names:
            blocked=_conflicts_with(r['then_subject'],kept_names,graph)
            conflicts.append({'subject':r['then_subject'],'rule':r,'reason':'与同批保留的建议互斥，优先保留可共存科目更多的一组','blocked_by':blocked})
    return kept,sorted(conflicts,key=lambda x:x['subject'])

def recommend(baskets,subjects,mutex_pairs=None):
    mutex_pairs=mutex_pairs or []
    source=[set(x)for x in baskets];rng=np.random.default_rng(38);indices=rng.permutation(len(source));tr=indices[:72];te=indices[72:];rules=apriori([source[i]for i in tr]);hit=0;covered=0;cases=[]
    for i in te:
        basket=sorted(source[i]);hidden=basket[int(rng.integers(0,len(basket)))];visible=set(basket)-{hidden}
        raw_guesses={r['then_subject']for r in rules if set(r['if_subjects'])<=visible and r['then_subject']not in visible}
        # 留出评估与每批建议同一套互斥限制
        kept_guesses,case_conflicts=apply_mutex([r for r in rules if r['then_subject']in raw_guesses],visible,mutex_pairs)
        guesses={r['then_subject']for r in kept_guesses}
        hit+=hidden in guesses;covered+=bool(guesses)
        cases.append({'basket_index':int(i),'visible':sorted(visible),'hidden':hidden,'recommended':sorted(guesses),'excluded_by_mutex':case_conflicts,'hit':hidden in guesses})
    current=set(subjects)
    fired=[r for r in rules if set(r['if_subjects'])<=current and r['then_subject']not in current]
    suggested,conflicts=apply_mutex(fired,current,mutex_pairs)
    return {'algorithm':'Apriori train-only itemset support + association rules','seed':38,'train_rows':len(tr),'holdout_rows':len(te),'train_indices':tr.tolist(),'holdout_indices':te.tolist(),'source_checksum':hashlib.sha256(json.dumps([sorted(x)for x in source],ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),'min_support':.15,'min_confidence':.6,'min_lift':1,'mutex_pairs':[sorted(p)for p in sorted(mutex_pairs)],'rules':rules,'suggestions':suggested,'suggestion_conflicts':conflicts,'input_subjects':sorted(current),'holdout_hidden_item_recall':round(hit/len(te),4),'holdout_recommendation_coverage':round(covered/len(te),4),'holdout_cases':cases}
