from io import BytesIO

from PIL import Image

from app.core.config import get_settings
from app.cv import adapter
from app.integrations.triton import TritonClient, TritonError


def create_job(client, external=False, invalid=False):
    workspace = client.post('/api/v1/workspaces', json={'slug': 'inference-test', 'name': 'Test'}).json()
    wid = workspace['id']
    if external:
        response = client.post('/api/v1/media', json={'workspace_id': wid, 'url': 'http://example.test/file.jpg'})
    else:
        buf = BytesIO()
        Image.new('RGB', (32, 24), 'white').save(buf, format='PNG')
        content = b'\x89PNG\r\n\x1a\ninvalid' if invalid else buf.getvalue()
        response = client.post('/api/v1/media/upload', data={'workspace_id': wid},
                               files={'file': ('sample.png', content, 'image/png')})
    assert response.status_code == 201, response.text
    media = response.json()
    response = client.post('/api/v1/jobs', json={'workspace_id': wid, 'media_id': media['id'], 'pipeline': 'detection'})
    assert response.status_code == 201
    return response.json()['id'], media['id']


def findings(client, job_id):
    return client.get('/api/v1/findings', params={'job_id': job_id}).json()


def test_mock_persistence_and_feed(client, monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'mock')
    job, media = create_job(client)
    url = f'/api/v1/jobs/{job}/run'
    response = client.post(url)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'succeeded'
    assert response.json()['result']['mode'] == 'mock'
    items = findings(client, job)
    assert len(items) == 1 and items[0]['source'] == 'mock'
    assert items[0]['attributes']['synthetic'] is True
    assert items[0]['geometry']['coordinate_space'] == 'normalized'
    assert client.post(url).status_code == 409
    assert len(findings(client, job)) == 1
    feed = client.get('/api/v1/inspection/frames', params={'workspace': 'inference-test'}).json()
    assert feed['frames'][0]['id'] == media
    assert feed['frames'][0]['findings'][0]['id'] == items[0]['id']


def test_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'disabled')
    job, _ = create_job(client)
    assert client.post(f'/api/v1/jobs/{job}/run').status_code == 503
    assert client.get(f'/api/v1/jobs/{job}').json()['status'] == 'queued'


def test_external_media_rejected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'mock')
    job, _ = create_job(client, external=True)
    assert client.post(f'/api/v1/jobs/{job}/run').status_code == 422
    assert not findings(client, job)


def test_bad_image(client, monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'mock')
    job, _ = create_job(client, invalid=True)
    assert client.post(f'/api/v1/jobs/{job}/run').json()['status'] == 'failed'
    assert not findings(client, job)


def test_unconfigured_adapter(client, monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'triton')
    job, _ = create_job(client)
    result = client.post(f'/api/v1/jobs/{job}/run').json()
    assert result['status'] == 'failed'
    assert result['error_message'] == 'CV adapter is not configured'
    assert not findings(client, job)


def install_fake_adapter(monkeypatch):
    monkeypatch.setattr(get_settings(), 'inference_mode', 'triton')
    monkeypatch.setattr(adapter, 'preprocess', lambda image, params: adapter.PreparedInput(
        [{'name': 'input', 'datatype': 'FP32', 'shape': [1], 'data': [1.0]}], ['output']))
    monkeypatch.setattr(adapter, 'postprocess', lambda outputs, image, prepared, params: [
        adapter.Detection(category='pole', score=outputs['output']['data'][0], x=0.1, y=0.1, width=0.2, height=0.7)])


def test_triton_pipeline_with_test_double(client, monkeypatch):
    install_fake_adapter(monkeypatch)
    def fake_infer(self, model, version, inputs, output_names):
        assert (model, version, output_names) == ('detection', '1', ['output'])
        return {'output': {'data': [0.8]}}
    monkeypatch.setattr(TritonClient, 'infer', fake_infer)
    job, _ = create_job(client)
    assert client.post(f'/api/v1/jobs/{job}/run').json()['status'] == 'succeeded'
    item = findings(client, job)[0]
    assert item['source'] == 'triton' and item['score'] == 0.8
    assert item['attributes']['synthetic'] is False


def test_triton_failure(client, monkeypatch):
    install_fake_adapter(monkeypatch)
    def fail(*args, **kwargs):
        raise TritonError('private upstream detail')
    monkeypatch.setattr(TritonClient, 'infer', fail)
    job, _ = create_job(client)
    result = client.post(f'/api/v1/jobs/{job}/run').json()
    assert result['status'] == 'failed'
    assert result['error_message'] == 'Triton inference failed'
    assert not findings(client, job)
