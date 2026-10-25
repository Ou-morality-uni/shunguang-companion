import hashlib
import io

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from backend.app import main, runtime
from backend.app.store import Store


def test_full_pdf_preview_preserves_all_pages_and_checks_the_version(tmp_path, monkeypatch):
    store = Store(tmp_path / 'preview.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    stream = io.BytesIO()
    canvas = Canvas(stream)
    for page in range(3):
        canvas.drawString(40, 700, f'Original page {page + 1}')
        canvas.showPage()
    canvas.save()
    data = stream.getvalue()
    version = hashlib.sha256(data).hexdigest()
    with TestClient(main.app) as client:
        cid = store.create_conversation()['id']
        file_id = client.post('/api/work/upload?name=source.pdf', content=data).json()['task']['id']
        url = f'/api/work/resources/attachment/{file_id}/document'
        response = client.get(url, params={'version': version})
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/pdf'
        assert response.content == data
        assert client.get(url, params={'version': '0' * 64}).status_code == 409
        annotation = client.post(
            '/api/work/annotations',
            json={
                'conversation_id': cid,
                'source': {'kind': 'attachment', 'id': file_id, 'version': version},
                'target_id': 'page:3',
                'quote': 'Original page 3',
                'comment': 'Shorten this sentence',
                'regions': [{'page': 3, 'rect': [0.1, 0.1, 0.6, 0.1]}],
                'text_origin': 'native',
            },
        )
        assert annotation.status_code == 201, annotation.text
        assert annotation.json()['regions'][0]['page'] == 3
        invalid = annotation.json()
        payload = {
            key: invalid[key]
            for key in ('conversation_id', 'source', 'target_id', 'quote', 'comment', 'regions', 'text_origin')
        }
        payload['quote'] = 'Not in the original document'
        assert client.post('/api/work/annotations', json=payload).status_code == 409


def test_upload_records_are_compact_and_do_not_expose_local_paths(tmp_path, monkeypatch):
    store = Store(tmp_path / 'uploads.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    with TestClient(main.app) as client:
        uploaded = client.post('/api/work/upload?name=notes.txt', content=b'Notes').json()['task']
        records = client.get('/api/work/uploads').json()
        assert records == [
            {'id': uploaded['id'], 'name': 'notes.txt', 'bytes': 5, 'created_at': uploaded['created_at']}
        ]
        assert not any(key in records[0] for key in ('path', 'steps', 'workspace_id'))


def test_word_page_quote_resolves_only_a_unique_original_paragraph(tmp_path, monkeypatch):
    from docx import Document

    from backend.app import office_resources

    store = Store(tmp_path / 'word.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    document = Document()
    document.add_paragraph('Original editable paragraph')
    raw = io.BytesIO()
    document.save(raw)
    rendered = io.BytesIO()
    canvas = Canvas(rendered)
    canvas.drawString(50, 700, 'Original editable paragraph')
    canvas.save()
    monkeypatch.setattr(office_resources, 'preview_pdf', lambda *args: rendered.getvalue())
    with TestClient(main.app) as client:
        cid = store.create_conversation()['id']
        identity = client.post('/api/work/upload?name=source.docx', content=raw.getvalue()).json()['task']['id']
        response = client.post(
            '/api/work/annotations',
            json={
                'conversation_id': cid,
                'source': {'kind': 'attachment', 'id': identity, 'version': hashlib.sha256(raw.getvalue()).hexdigest()},
                'target_id': 'page:1',
                'quote': 'Original editable paragraph',
                'comment': 'Revise this paragraph',
                'regions': [{'page': 1, 'rect': [0.1, 0.1, 0.8, 0.1]}],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()['target_id'] == 'p:0'


def test_image_comments_reject_nonexistent_pages_and_label_ocr_as_unverified(tmp_path, monkeypatch):
    from PIL import Image

    store = Store(tmp_path / 'image.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    output = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(output, format='PNG')
    raw = output.getvalue()
    with TestClient(main.app) as client:
        cid = store.create_conversation()['id']
        identity = client.post('/api/work/upload?name=image.png', content=raw).json()['task']['id']
        payload = {
            'conversation_id': cid,
            'source': {'kind': 'attachment', 'id': identity, 'version': hashlib.sha256(raw).hexdigest()},
            'target_id': 'image',
            'comment': 'Revise this image',
            'regions': [{'page': 2, 'rect': [0.1, 0.1, 0.2, 0.2]}],
        }
        assert client.post('/api/work/annotations', json=payload).status_code == 422
        payload.update(
            text_origin='ocr', quote='Unverified recognized text', regions=[{'page': 1, 'rect': [0.1, 0.1, 0.2, 0.2]}]
        )
        response = client.post('/api/work/annotations', json=payload)
        assert response.status_code == 201, response.text
        assert 'OCR' in response.json()['location']
