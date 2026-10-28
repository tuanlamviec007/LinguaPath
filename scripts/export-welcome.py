#!/usr/bin/env python3
"""Export public learning demos as static Pages assets, without a database."""
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP_ORIGIN = 'https://linguapath-app.onrender.com'


def export(destination):
    os.environ.update(DATABASE_URL='sqlite:///:memory:', DJANGO_DEBUG='true',
                      AI_TUTOR_ENABLED='false', SOCIAL_AUTH_ENABLED='false',
                      DJANGO_ALLOWED_HOSTS='testserver,localhost,127.0.0.1')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.test import Client
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    output = Path(destination).resolve()
    output.mkdir(parents=True, exist_ok=True)
    client = Client()
    pages = [('index.html', '/', {}), ('learn/start/index.html', '/learn/start/', {})]
    pages += [(f'demo/{answer}/index.html', '/', {'demo_answer': answer}) for answer in 'ABC']
    for name, path, query in pages:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(path, query)
        if response.status_code != 200 or queries:
            raise RuntimeError('Public export must succeed without database queries')
        html = response.content.decode()
        # Only public home/help/static assets remain on Pages. App activity
        # always uses the existing Django origin and its own session cookies.
        def link(match):
            attr, quote, value = match.groups()
            if value.startswith('/') and not value.startswith('//'):
                local = value == '/' or value.startswith('/#') or value.startswith('/learn/start/') or value.startswith('/static/')
                if not local:
                    value = APP_ORIGIN + value
            return f'{attr}={quote}{value}{quote}'
        html = re.sub(r'''(href|action)=(['"])(.*?)\2''', link, html)
        # Native GET fallback has a separate static page for every answer.
        for answer in 'ABC':
            html = html.replace(f'name="demo_answer" value="{answer}"',
                                f'formaction="/demo/{answer}/#quick-demo" name="demo_answer" value="{answer}"')
        if 'csrfmiddlewaretoken' in html:
            raise RuntimeError('Private forms must never enter the static export')
        file = output / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(html, encoding='utf-8')
    shutil.copytree(ROOT / 'static', output / 'static', dirs_exist_ok=True)
    (output / '404.html').write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><title>LinguaPath</title><h1>Trang này chưa có.</h1><p><a href="/">Về trang chủ</a> · <a href="'+APP_ORIGIN+'/accounts/login/">Đăng nhập để học tiếp</a></p></html>', encoding='utf-8')
    (output / '_headers').write_text('/*\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Referrer-Policy: strict-origin-when-cross-origin\n  Cache-Control: public, max-age=300\n', encoding='utf-8')
    print('Public Pages export ready: no Functions, database, learner data or credentials.')


if __name__ == '__main__':
    export(sys.argv[1] if len(sys.argv) > 1 else 'build/welcome')
