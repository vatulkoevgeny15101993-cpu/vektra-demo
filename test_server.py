import io
import json
import tempfile
import unittest
from pathlib import Path
import server


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.DB = str(Path(self.tmp.name) / 'test.sqlite3')
        server.PASSWORD = 'test-password-at-least-16'
        server.PUBLIC_URL = 'http://localhost:8000'
        server.init_db()
        self.cookie = ''

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method='GET', data=None, origin='http://localhost:8000', cookie=None):
        raw = json.dumps(data or {}).encode()
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'CONTENT_TYPE':'application/json',
               'CONTENT_LENGTH':str(len(raw)), 'wsgi.input':io.BytesIO(raw),
               'HTTP_ORIGIN':origin,'REMOTE_ADDR':'127.0.0.1','HTTP_COOKIE':self.cookie if cookie is None else cookie}
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        payload = b''.join(server.app(env, start))
        response['body'] = json.loads(payload) if response['headers']['Content-Type'].startswith('application/json') else payload
        return response

    def login(self):
        result=self.call('/api/login','POST',{'password':server.PASSWORD})
        self.assertEqual(result['status'],200)
        self.cookie=result['headers']['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',result['headers']['Set-Cookie'])
        self.assertIn('SameSite=Strict',result['headers']['Set-Cookie'])

    def submit(self, **kwargs):
        data={'email':'test@example.com','company':'Компания <test>','contact':'Анна','website':'https://example.com','plan':'Professional','consent':True}
        data.update(kwargs)
        return self.call('/api/requests','POST',data)

    def test_complete_persisted_workflow(self):
        result=self.submit()
        self.assertEqual(result['status'],201)
        lead_id=result['body']['id']
        # A fresh initialization/connection does not discard persisted data.
        server.init_db()
        self.assertEqual(self.call('/api/leads')['status'],401)
        self.login()
        leads=self.call('/api/leads')['body']['leads']
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0]['email'],'test@example.com')
        self.assertEqual(leads[0]['score']['points'],80)
        self.assertGreater(leads[0]['consent_at'],0)
        draft=self.call(f'/api/leads/{lead_id}/draft','POST',{})
        self.assertEqual(draft['status'],200)
        self.assertIn('Анна',draft['body']['draft'])
        self.assertIn('Professional',draft['body']['draft'])
        self.assertEqual(self.call(f'/api/leads/{lead_id}','PATCH',{'status':'meeting','notes':'Позвонить завтра','draft':'Мой текст'})['status'],200)
        lead=self.call('/api/leads')['body']['leads'][0]
        self.assertEqual(lead['notes'],'Позвонить завтра')
        self.assertEqual(lead['draft'],'Мой текст')
        self.assertEqual(lead['score']['points'],100)
        self.assertEqual(self.call(f'/api/leads/{lead_id}','DELETE',{})['status'],200)
        self.assertEqual(self.call('/api/leads')['body']['leads'],[])
        self.assertEqual(self.call('/api/logout','POST',{})['status'],200)
        self.assertEqual(self.call('/api/leads')['status'],401)

    def test_validation(self):
        for fields in [{'email':'invalid'},{'company':''},{'consent':False},{'website':'javascript:alert(1)'},{'plan':'Unknown'},{'email':['x']},{'company':'x'*201},{'website':'http://[broken'},{'contact':'\ud800'}]:
            self.assertEqual(self.submit(**fields)['status'],400, fields)
        self.login()
        self.assertEqual(self.call('/api/leads/999','PATCH',{'status':'meeting'})['status'],404)
        lead_id=self.submit()['body']['id']
        self.assertEqual(self.call(f'/api/leads/{lead_id}','PATCH',{'status':'arbitrary'})['status'],400)

    def test_auth_origin_and_limits(self):
        self.assertEqual(self.call('/api/login','POST',{'password':'wrong'})['status'],401)
        self.assertEqual(self.call('/api/login','POST',{'password':server.PASSWORD},origin='https://evil.example')['status'],403)
        self.assertEqual(self.call('/api/requests','POST',{},origin='')['status'],403)
        self.assertEqual(self.call('/api/leads',cookie='vektra_session=forged')['status'],401)
        self.assertEqual(self.call('/api/leads/1','DELETE',{})['status'],401)
        for _ in range(9):
            self.call('/api/login','POST',{'password':'wrong'})
        self.assertEqual(self.call('/api/login','POST',{'password':server.PASSWORD})['status'],429)

    def test_request_rate_limit(self):
        for _ in range(20):
            self.assertEqual(self.submit()['status'],201)
        self.assertEqual(self.submit()['status'],429)

    def test_static_allowlist_and_health(self):
        for path in ('/','/admin','/app.js','/admin.js','/service.css','/theme.css','/health'):
            self.assertEqual(self.call(path)['status'],200,path)
        for path in ('/server.py','/.env','/data/vektra.sqlite3','/../server.py'):
            self.assertEqual(self.call(path)['status'],404,path)
        self.assertIn('Content-Security-Policy',self.call('/')['headers'])

    def test_session_expiry_and_https(self):
        self.login()
        with server.connect() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.call('/api/leads')['status'],401)
        server.PUBLIC_URL='https://vektra.example'
        result=self.call('/api/login','POST',{'password':server.PASSWORD},origin=server.PUBLIC_URL)
        self.assertIn('; Secure',result['headers']['Set-Cookie'])

    def test_config_rejects_weak_password(self):
        server.PASSWORD='weak'
        with self.assertRaises(RuntimeError):
            server.validate_config()


if __name__=='__main__':
    unittest.main()
