import os,time,json,logging
from pathlib import Path
import redis
from sqlalchemy import select
from .db import Session
from .models import Pack,PackLine,Edition,HistoricalBasket
from .common import lock
from .constraints import mutex_pairs,mutex_checksum
from .basket_rules import recommend
q=redis.Redis.from_url(os.environ['REDIS_URL'],decode_responses=True)
def process_pack(s,pack_id):
    p=lock(s,Pack,pack_id)
    if p.ml_state!='queued':return p
    p.ml_state='running';p.error=None;s.commit()
    try:
        pairs=mutex_pairs(s);checksum_at_start=mutex_checksum(pairs)
        baskets=list(s.scalars(select(HistoricalBasket.subjects).order_by(HistoricalBasket.id)));subjects=list(s.scalars(select(Edition.subject).join(PackLine,PackLine.edition_id==Edition.id).where(PackLine.pack_id==p.id)))
        result=recommend(baskets,subjects,pairs)
        result['constraints_checksum']=checksum_at_start
        # 分析并发期间互斥关系被改动：结果按旧限制算出，只能留档，不可发布
        if mutex_checksum(mutex_pairs(s))!=checksum_at_start:
            p.recommendation=result;p.ml_state='stale';p.error='分析期间互斥关系已变更，请重新分析后再发布'
        else:
            p.recommendation=result;p.ml_state='ready';p.error=None
        Path(f'/artifacts/basket-{p.id}.json').write_text(json.dumps(result,ensure_ascii=False));s.commit()
    except Exception as ex:
        p.ml_state='failed';p.error=str(ex)[:450];s.commit();logging.exception('basket failed')
    return p
if __name__=='__main__':
    while True:
        Path('/tmp/books-heartbeat').touch()
        try:
            item=q.blpop('book-baskets',timeout=2)
            if not item:continue
            with Session()as s:process_pack(s,int(item[1]))
        except Exception:logging.exception('queue unavailable');time.sleep(1)
