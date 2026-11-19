import hashlib
import json
from sqlalchemy import select
from fastapi import HTTPException
from .models import SubjectMutex,Pack
from .common import audit

def normalize_pair(a,b):
    # 互斥是无向关系：统一按字典序存半边，靠唯一约束去重
    a=(a or '').strip();b=(b or '').strip()
    if not a or not b:raise HTTPException(422,'互斥两侧都必须填写课程代码')
    if a==b:raise HTTPException(409,'互斥关系必须是两门不同课程')
    return (a,b)if a<b else(b,a)

def mutex_pairs(s):
    rows=s.scalars(select(SubjectMutex).order_by(SubjectMutex.subject_a,SubjectMutex.subject_b)).all()
    return [[x.subject_a,x.subject_b]for x in rows]

def mutex_checksum(pairs):
    canonical=json.dumps(sorted([sorted(p)for p in pairs]),ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(canonical.encode()).hexdigest()

def add_mutex(s,d,u):
    a,b=normalize_pair(d.subject_a,d.subject_b)
    exists=s.scalar(select(SubjectMutex.id).where(SubjectMutex.subject_a==a,SubjectMutex.subject_b==b))
    if exists:raise HTTPException(409,'这两门课程的互斥关系已经登记')
    x=SubjectMutex(subject_a=a,subject_b=b,reason=(d.reason or '').strip()[:250]);s.add(x);s.flush()
    _expire_ready(s)
    audit(s,u,'登记课程互斥 '+a+' / '+b)
    return {'id':x.id,'subject_a':a,'subject_b':b,'reason':x.reason,'constraints_checksum':mutex_checksum(mutex_pairs(s))}

def delete_mutex(s,id,u):
    x=s.get(SubjectMutex,id)
    if not x:raise HTTPException(404,'互斥关系不存在')
    pair=x.subject_a+' / '+x.subject_b;s.delete(x);s.flush()
    _expire_ready(s)
    audit(s,u,'解除课程互斥 '+pair)
    return {'removed':pair,'constraints_checksum':mutex_checksum(mutex_pairs(s))}

def _expire_ready(s):
    # 改互斥关系时，按旧限制算出且尚未发布的建议立即不可发布；已发布留档不动
    for p in s.scalars(select(Pack).where(Pack.ml_state=='ready')).all():
        p.ml_state='stale';p.error='互斥关系已变更，旧分析结果不可发布，请重新分析'

def snapshot(s):
    pairs=mutex_pairs(s)
    return {'mutex_pairs':pairs,'constraints_checksum':mutex_checksum(pairs)}
