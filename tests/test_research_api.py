"""HTTP lifecycle and persisted evidence contracts for finite paired sessions."""
import hashlib
import json
import zipfile
from io import BytesIO
import asyncio
from types import SimpleNamespace
from rts_predictive.api.server import app


class ASGIClient:
    """Exercise real ASGI routing/validation without optional HTTP test packages."""
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def request(self,method,path,**kwargs):
        async def invoke():
            body=json.dumps(kwargs.get('json',{})).encode();messages=[]
            scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
                   'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
                   'root_path':'','headers':[(b'content-type',b'application/json')],
                   'client':('127.0.0.1',1),'server':('test',80)}
            async def receive():return {'type':'http.request','body':body,'more_body':False}
            async def send(message):messages.append(message)
            await app(scope,receive,send)
            status=next(m['status'] for m in messages if m['type']=='http.response.start')
            content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
            return SimpleNamespace(status_code=status,content=content,json=lambda:json.loads(content))
        return asyncio.run(invoke())
    def get(self,path,**kwargs):return self.request('GET',path,**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)
    def delete(self,path,**kwargs):return self.request('DELETE',path,**kwargs)


def test_research_session_http_and_persisted_downloads():
    with ASGIClient() as client:
        assert client.post('/api/research/sessions',json={'family':'imaginary'}).status_code==422
        assert client.post('/api/research/sessions',json={'release_end_us':1}).status_code==422
        response=client.post('/api/research/sessions',json={'seed':1099,'release_end_us':100000})
        assert response.status_code==201
        initial=response.json();uid=initial['session_id'];base='/api/research/sessions/'+uid
        assert initial['budgets']['inference_work_us']==250
        assert len(initial['devices'])==4
        assert sum(len(w['tasks']) for w in initial['workflows'])==11
        assert client.get(base+'/artifacts/edf/metrics.json').status_code==409
        assert client.post(base+'/step',json={'delta_us':0}).status_code==422
        x=initial
        while x['phase']!='COMPLETE':
            response=client.post(base+'/step',json={'delta_us':100000})
            assert response.status_code==200
            x=response.json()
        assert x['comparison']['final']
        assert not x['before']['metrics']['pending_jobs']
        timing=client.get(base+'/artifacts/protected/inference-timing.json').json()
        assert timing['sample_count']==x['host_latency']['count']
        assert timing['observed_max_us']==x['host_latency']['observed_max_us']
        assert not timing['hard_wcet_proven']
        for policy in ['edf','protected']:
            m=client.get(base+'/artifacts/'+policy+'/manifest.json').json()
            events=client.get(base+'/artifacts/'+policy+'/events.jsonl').content
            assert hashlib.sha256(events).hexdigest()==m['event_sha256']
            metrics=client.get(base+'/artifacts/'+policy+'/metrics.json').content
            assert hashlib.sha256(metrics).hexdigest()==m['metrics_sha256']
            assert len(events.splitlines())==m['event_count']
            assert m['environment']['torch']
        archived=client.get(base+'/evidence/source.zip').content
        assert hashlib.sha256(archived).hexdigest()==m['source_archive_sha256']
        with zipfile.ZipFile(BytesIO(archived)) as z:
            assert 'rts_predictive/simulator/research_engine.py' in z.namelist()
            assert 'models/research_gnn.pt' in z.namelist()
            assert 'frontend/facility-scene.js' in z.namelist()
            assert 'frontend/index.html' in z.namelist()
            assert 'UI Design.md' in z.namelist()
        certificate=client.get(base+'/evidence/analytical-reference.json').json()
        assert certificate['applies_to_live_scheduler'] is False
        assert client.delete(base).status_code==204
        assert client.get(base).status_code==404
        # Closed/evicted sessions retain audit files independently of RAM.
        assert client.get(base+'/artifacts/protected/metrics.json').status_code==200
        assert client.get(base+'/evidence/config.json').status_code==200
        assert client.get(base+'/evidence/forbidden.txt').status_code==422
        assert client.get('/api/research/sessions/not-a-uuid/artifacts/edf/metrics.json').status_code==404
