import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.integrations.triton import TritonClient, TritonError


@pytest.fixture
def fake_triton():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, body))
            if body['inputs'][0]['name'] == 'fail':
                self.send_error(503)
                return
            data = json.dumps({'outputs': [{'name': 'out', 'shape': [1],
                                            'datatype': 'FP32', 'data': [0.5]}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield TritonClient(f'http://127.0.0.1:{server.server_port}'), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_infer(fake_triton):
    client, requests = fake_triton
    inputs = [{'name': 'in', 'shape': [1], 'datatype': 'FP32', 'data': [1.0]}]
    assert client.infer('detection', '1', inputs, ['out'])['out']['data'] == [0.5]
    assert requests == [('/v2/models/detection/versions/1/infer',
                         {'inputs': inputs, 'outputs': [{'name': 'out'}]})]


def test_http_failure(fake_triton):
    client, _ = fake_triton
    with pytest.raises(TritonError):
        client.infer('detection', '1', [{'name': 'fail'}], ['out'])


def test_unexpected_output(fake_triton):
    client, _ = fake_triton
    with pytest.raises(TritonError):
        client.infer('detection', '1', [{'name': 'in'}], ['missing'])


def test_invalid_model_path():
    with pytest.raises(ValueError):
        TritonClient.model_path('../other', '1')
