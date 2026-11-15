import httpx
import pytest
from metis.providers import Providers, ProviderUnavailable

@pytest.mark.parametrize('host', ['ai.mongodb.com', 'api.voyageai.com'])
def test_embedding_routes_only_to_selected_trusted_host(monkeypatch, host):
    seen=[]
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(200, json={'data':[{'index':0,'embedding':[1.0]}]})
    original=httpx.Client
    monkeypatch.setenv('METIS_VOYAGE_API_HOST',host)
    monkeypatch.setattr(httpx,'Client',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    result=Providers(None,type('Config',(),{'provider_file':''})())._request({'provider':'voyage','model':'voyage-4'},'test-secret',{'texts':['math']},False)
    assert seen==[host]
    assert result['embeddings']==[[1.0]]

def test_embedding_rejects_arbitrary_host(monkeypatch):
    monkeypatch.setenv('METIS_VOYAGE_API_HOST','attacker.example')
    with pytest.raises(ProviderUnavailable,match='Unsupported embedding API host'):
        Providers(None,type('Config',(),{'provider_file':''})())._request({'provider':'voyage','model':'voyage-4'},'test-secret',{'texts':['math']},False)


def test_reasoning_payload_preserves_math_without_vectors():
    from metis.providers import reasoning_payload
    source={'nodes':[{'statement':'A implies B','embedding':[.1,.2],'evidence':[{'source':'paper','excerpt':'Hypothesis H'}]}]}
    assert reasoning_payload(source)=={'nodes':[{'statement':'A implies B','evidence':[{'source':'paper','excerpt':'Hypothesis H'}]}]}
    assert source['nodes'][0]['embedding']==[.1,.2]
