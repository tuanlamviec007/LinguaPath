#!/usr/bin/env python3
"""Dump and restore disposable CI data. Never accepts a production database."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql


class RestoreFailure(Exception):
    pass


def validate_config(database_url, env, platform=None):
    if not (platform or sys.platform).startswith('linux') or env.get('CI') != 'true' or env.get('GITHUB_ACTIONS') != 'true':
        raise RestoreFailure('disposable_github_ci_required')
    try:
        p = urlsplit(database_url)
        valid = (p.scheme in ('postgres', 'postgresql') and p.hostname == '127.0.0.1'
                 and p.port in (None, 5432) and p.username == 'linguapath_ci'
                 and p.path == '/linguapath_ci' and p.password
                 and not p.query and not p.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise RestoreFailure('disposable_loopback_database_required')
    return p


def fingerprints(dsn):
    result = {}
    with psycopg.connect(dsn) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
        for (table,) in tables:
            digest, count = hashlib.sha256(), 0
            with conn.cursor(name='restore_fingerprint') as cursor:
                cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(sql.Identifier('public', table)))
                for (row,) in cursor:
                    digest.update(row.encode())
                    digest.update(b'\n')
                    count += 1
            result[table] = (count, digest.hexdigest())
        sequences = conn.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall()
        result['__sequences__'] = (len(sequences), hashlib.sha256(json.dumps(sequences).encode()).hexdigest())
    return result


SEED = r'''
import django, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from planner.models import LearnerProfile
from learning.models import VocabularyQuizSession
user = get_user_model().objects.create_user(username=os.environ['RESTORE_USERNAME'], password=os.environ['RESTORE_PASSWORD'])
LearnerProfile.objects.create(user=user, onboarding_complete=True)
client = Client()
assert client.login(username=user.username, password=os.environ['RESTORE_PASSWORD'])
response = client.post(reverse('learning:quiz_start'), {'count':'5'})
assert response.status_code == 302
quiz = VocabularyQuizSession.objects.get(user=user, status='in_progress')
answer = quiz.snapshot[0]['correct_key']
response = client.post(reverse('learning:quiz_draft', args=[quiz.pk]), {'revision':'0', 'answer_1':answer})
assert response.status_code == 200
with open(os.environ['RESTORE_RECEIPT'], 'w') as handle:
    json.dump({'quiz':quiz.pk, 'session':client.cookies[settings.SESSION_COOKIE_NAME].value, 'answer':answer}, handle)
'''
VERIFY = r'''
import django, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from learning.models import VocabularyQuizSession
from io import StringIO
with open(os.environ['RESTORE_RECEIPT']) as handle:
    receipt=json.load(handle)
user=get_user_model().objects.get(username=os.environ['RESTORE_USERNAME'])
assert user.check_password(os.environ['RESTORE_PASSWORD'])
quiz=VocabularyQuizSession.objects.get(pk=receipt['quiz'],user=user,status='in_progress')
assert quiz.draft_revision==1 and quiz.draft_answers=={'1':receipt['answer']}
client=Client()
client.cookies[settings.SESSION_COOKIE_NAME]=receipt['session']
response=client.get(reverse('learning:quiz_take',args=[quiz.pk]))
assert response.status_code==200 and response.wsgi_request.user.pk==user.pk
assert client.login(username=user.username,password=os.environ['RESTORE_PASSWORD'])
call_command('check_schema',stdout=StringIO())
'''
CLEAN = r'''
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from django.contrib.auth import get_user_model
assert os.environ['RESTORE_USERNAME'].startswith('ci_restore_')
get_user_model().objects.filter(username=os.environ['RESTORE_USERNAME'],is_staff=False,is_superuser=False).delete()
from django.contrib.sessions.models import Session
import json
try:
    with open(os.environ['RESTORE_RECEIPT']) as handle:
        Session.objects.filter(session_key=json.load(handle)['session']).delete()
except FileNotFoundError:
    pass
'''


def run_python(code, env):
    subprocess.run([sys.executable, '-c', code], env=env, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=120)


def main():
    source = os.environ.get('DATABASE_URL', '')
    parsed = validate_config(source, os.environ)
    target = 'linguapath_restore_' + uuid4().hex
    restored = urlunsplit(parsed._replace(path='/' + target))
    env = dict(os.environ, RESTORE_USERNAME='ci_restore_' + uuid4().hex,
               RESTORE_PASSWORD=secrets.token_urlsafe(32), DJANGO_DEBUG='true',
               DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,testserver', AI_TUTOR_ENABLED='false')
    global CURRENT_STAGE
    created = seeded = False
    try:
        with TemporaryDirectory(prefix='linguapath-restore-') as directory:
            receipt = Path(directory) / 'receipt.json'
            env['RESTORE_RECEIPT'] = str(receipt)
            CURRENT_STAGE = 'seed'
            seeded = True
            run_python(SEED, env)
            receipt.chmod(0o600)
            CURRENT_STAGE = 'source_fingerprint'
            before = fingerprints(source)
            dump = Path(directory) / 'backup.dump'
            CURRENT_STAGE = 'dump'
            docker_env = dict(os.environ, PGPASSWORD=unquote(parsed.password))
            docker = ['docker', 'run', '--rm', '--network', 'host', '-e', 'PGPASSWORD']
            args = ['-h', '127.0.0.1', '-p', str(parsed.port or 5432), '-U', 'linguapath_ci']
            with dump.open('xb') as handle:
                dump.chmod(0o600)
                subprocess.run(docker + ['postgres:16', 'pg_dump', *args, '-d', 'linguapath_ci',
                               '--format=custom', '--no-owner', '--no-acl'], env=docker_env,
                               stdout=handle, stderr=subprocess.DEVNULL, check=True, timeout=180)
            CURRENT_STAGE = 'create_target'
            with psycopg.connect(source, autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
                created = True
            CURRENT_STAGE = 'restore'
            with dump.open('rb') as handle:
                subprocess.run(docker + ['-i', 'postgres:16', 'pg_restore', *args, '-d', target,
                               '--exit-on-error', '--no-owner', '--no-acl'], env=docker_env,
                               stdin=handle, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=True, timeout=180)
            CURRENT_STAGE = 'compare'
            if before != fingerprints(restored):
                raise RestoreFailure('restored_rows_differ')
            CURRENT_STAGE = 'verify_journey'
            run_python(VERIFY, dict(env, DATABASE_URL=restored))
            report = {'ok': True, 'scope': 'Disposable CI PostgreSQL only; not production backup/retention acceptance.',
                              'tables_verified': len(before), 'rows_verified': sum(row[0] for row in before.values()),
                              'session_and_quiz_draft_restored': True}
    finally:
        # Only a database successfully created by this invocation may be dropped.
        try:
            if created:
                with psycopg.connect(source, autocommit=True) as conn:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
        finally:
            if seeded:
                run_python(CLEAN, env)
    print(json.dumps(report))



CURRENT_STAGE = 'configuration'


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'ok': False, 'error': 'restore_rehearsal_failed', 'stage': CURRENT_STAGE}), file=sys.stderr)
        sys.exit(1)
