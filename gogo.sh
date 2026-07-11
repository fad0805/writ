#!/bin/bash
# 실행: bash gogo.sh [명령어]
# 호스트(서버)에서 실행하세요.

if [ "$1" = "fetch-log" ]; then
  docker compose logs api --tail 30

elif [ "$1" = "rebuild" ]; then
  git pull
  docker compose build api
  docker compose up -d

elif [ "$1" = "exec" ]; then
  docker compose exec api python3 -c "
import httpx
url = 'https://daydream.ink/@siarte/116895178885643677'
r = httpx.get(url, headers={'Accept': 'application/activity+json'}, follow_redirects=False)
print('status:', r.status_code)
print('location:', r.headers.get('location', 'no redirect'))
print('content-type:', r.headers.get('content-type'))
"

elif [ "$1" = "key-test" ]; then
  docker compose exec api python3 -c "
from app.crypto_utils import sign_string, verify_signature, get_private_key
from app.models import User, get_session
from app.config import SECRET_KEY
import time
with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    if not me: print('user not found'); exit()
    priv = get_private_key(me, SECRET_KEY)
    created = int(time.time())
    url = 'https://daydream.ink/@siarte/116895178885643677'
    from urllib.parse import urlparse
    parsed = urlparse(url)
    date = 'Thu, 10 Jul 2026 12:00:00 GMT'
    ss = '(request-target): get ' + parsed.path + '\nhost: ' + parsed.netloc + '\ndate: ' + date + '\n(request-created): ' + str(created)
    sig = sign_string(ss, priv)
    print('self-verify:', verify_signature(ss, sig, me.public_key))
    print('path:', parsed.path)
    print('host:', parsed.netloc)
    print('sig-header:', 'keyId=\"' + me.actor_uri() + '#main-key\",algorithm=\"hs2019\",created=\"' + str(created) + '\",headers=\"(request-target) host date (request-created)\",signature=\"' + sig + '\"')
"

elif [ "$1" = "actual-test" ]; then
  docker compose exec api python3 -c "
import httpx, time, datetime
from app.crypto_utils import sign_string, get_private_key
from app.models import User, get_session
from app.config import SECRET_KEY
from urllib.parse import urlparse

url = 'https://daydream.ink/@siarte/116895178885643677'
parsed = urlparse(url)
created = int(time.time())
date = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')

with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    priv = get_private_key(me, SECRET_KEY)
    ss = '(request-target): get ' + parsed.path + '\nhost: ' + parsed.netloc + '\ndate: ' + date + '\n(request-created): ' + str(created)
    sig = sign_string(ss, priv)
    sig_header = 'keyId=\"' + me.actor_uri() + '#main-key\",algorithm=\"hs2019\",created=\"' + str(created) + '\",headers=\"(request-target) host date (request-created)\",signature=\"' + sig + '\"'
    headers = {'Accept': 'application/activity+json', 'Signature': sig_header, 'Date': date, 'Host': parsed.netloc}
    r = httpx.get(url, headers=headers)
    print('status:', r.status_code)
    print('body:', r.text[:300])
"

elif [ "$1" = "try-legacy" ]; then
  docker compose exec api python3 -c "
import httpx, time, datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from app.models import User, get_session
from app.config import SECRET_KEY
from app.crypto_utils import get_private_key
from urllib.parse import urlparse

url = 'https://daydream.ink/@siarte/116895178885643677'
parsed = urlparse(url)
created = int(time.time())
date = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')

with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    priv_pem = get_private_key(me, SECRET_KEY)
    priv = serialization.load_pem_private_key(priv_pem.encode(), password=None)

    # PSS 시도
    ss = '(request-target): get ' + parsed.path + '\nhost: ' + parsed.netloc + '\ndate: ' + date + '\n(request-created): ' + str(created)
    sig_pss = priv.sign(ss.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    sig_pss_b64 = __import__('base64').b64encode(sig_pss).decode()
    headers_pss = {
        'Accept': 'application/activity+json',
        'Signature': 'keyId=\"' + me.actor_uri() + '#main-key\",algorithm=\"hs2019\",created=\"' + str(created) + '\",headers=\"(request-target) host date (request-created)\",signature=\"' + sig_pss_b64 + '\"',
        'Date': date, 'Host': parsed.netloc
    }
    r1 = httpx.get(url, headers=headers_pss)
    print('PSS hs2019 ->', r1.status_code, r1.json().get('error','')[:100])

    # PKCS1v15 + rsa-sha256 시도
    sig_pkcs = priv.sign(ss.encode(), padding.PKCS1v15(), hashes.SHA256())
    sig_pkcs_b64 = __import__('base64').b64encode(sig_pkcs).decode()
    headers_pkcs = {
        'Accept': 'application/activity+json',
        'Signature': 'keyId=\"' + me.actor_uri() + '#main-key\",algorithm=\"rsa-sha256\",headers=\"(request-target) host date (request-created)\",signature=\"' + sig_pkcs_b64 + '\"',
        'Date': date, 'Host': parsed.netloc
    }
    r2 = httpx.get(url, headers=headers_pkcs)
    print('PKCS1v15 rsa-sha256 ->', r2.status_code, r2.json().get('error','')[:100])
"

elif [ "$1" = "debug-path" ]; then
  docker compose exec api python3 -c "
import httpx
from app.models import User, get_session

with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    local_pub = me.public_key

print('=== 로컬 공개키 (처음 120자) ===')
print(local_pub[:120])

r_key = httpx.get('https://writ.daydream.ink/users/siarte', headers={'Accept': 'application/activity+json'})
if r_key.status_code == 200:
    remote_pub = r_key.json().get('publicKey', {}).get('publicKeyPem', '')
    print()
    print('=== daydream.ink가 조회한 공개키 (처음 120자) ===')
    print(remote_pub[:120])
    print()
    print('일치:', local_pub == remote_pub)
    print('로컬 길이:', len(local_pub), '리모트 길이:', len(remote_pub))
else:
    print('공개키 조회 실패:', r_key.status_code, r_key.text[:200])
"

elif [ "$1" = "raw-headers" ]; then
  docker compose exec api python3 -c "
import httpx, time, datetime
from app.crypto_utils import sign_string, get_private_key
from app.models import User, get_session
from app.config import SECRET_KEY
from urllib.parse import urlparse

url = 'https://daydream.ink/@siarte/116895178885643677'
parsed = urlparse(url)
created = int(time.time())
date = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')

with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    priv = get_private_key(me, SECRET_KEY)
    ss = '(request-target): get ' + parsed.path + '\nhost: ' + parsed.netloc + '\ndate: ' + date + '\n(request-created): ' + str(created)
    sig = sign_string(ss, priv)
    sig_header = 'keyId=\"' + me.actor_uri() + '#main-key\",algorithm=\"hs2019\",created=\"' + str(created) + '\",headers=\"(request-target) host date (request-created)\",signature=\"' + sig + '\"'
    headers = {'Accept': 'application/activity+json', 'Signature': sig_header, 'Date': date, 'Host': parsed.netloc}

# httpx가 실제로 보내는 헤더 확인
req = httpx.Request('GET', url, headers=headers)
print('=== 우리가 보낸 헤더 ===')
for k, v in req.headers.items():
    print(f'  {k}: {v}')
print()
print('Host 헤더(raw):', repr(req.headers.get('host')))
print('path:', repr(req.url.path))
"

elif [ "$1" = "debug-follow" ]; then
  docker compose exec api python3 -c "
from app.models import Follow, User, get_session
with get_session() as s:
    local = s.query(User).filter_by(username='siarte', is_remote=False).first()
    remote = s.query(User).filter_by(username='siarte@daydream.ink').first()
    if not local or not remote: print('users not found'); exit()
    f = s.query(Follow).filter_by(follower_id=local.id, following_id=remote.id).first()
    print('=== OUTGOING (writ→remote) ===')
    print('follow in DB:', f is not None)
    if f: print('accepted:', f.accepted)
    # Also check incoming
    f2 = s.query(Follow).filter_by(follower_id=remote.id, following_id=local.id).first()
    print('=== INCOMING (remote→writ) ===')
    print('follow in DB:', f2 is not None)
    if f2: print('accepted:', f2.accepted)
"

elif [ "$1" = "mastodon-poll" ]; then
  id="${2:-116901218746967775}"
  docker compose exec api python3 -c "
import httpx, json
url = 'https://daydream.ink/users/siarte/statuses/$id'
r = httpx.get(url, headers={'Accept': 'application/activity+json'})
if r.status_code == 200:
    d = r.json()
    obj = d.get('object', d)
    print('=== 마스토돈 투표 구조 ===')
    print('type:', obj.get('type'))
    print('endTime:', obj.get('endTime'))
    print('options:', json.dumps(obj.get('oneOf'), indent=2, ensure_ascii=False)[:500])
    print('to:', obj.get('to'))
    print('cc:', obj.get('cc'))
    print()
    # WRIT 투표와 비교
    r2 = httpx.get('https://writ.daydream.ink/@siarte/72871480', headers={'Accept':'application/activity+json'})
    if r2.status_code == 200:
        d2 = r2.json()
        obj2 = d2.get('object', d2)
        print('=== WRIT 투표 ===')
        print('options:', json.dumps(obj2.get('oneOf'), indent=2, ensure_ascii=False)[:500])
        print('to:', obj2.get('to'))
        print('cc:', obj2.get('cc'))
else:
    print('status:', r.status_code, r.text[:200])
"

elif [ "$1" = "check-poll" ]; then
  id="${2:-659dac71}"
  docker compose exec api python3 -c "
import httpx, json
r = httpx.get(f'https://writ.daydream.ink/@siarte/$id', headers={'Accept':'application/activity+json'})
d = r.json()
obj = d.get('object', d)
print('type:', obj.get('type'))
print('endTime:', obj.get('endTime'))
print('votersCount:', obj.get('votersCount'))
print('options:', json.dumps(obj.get('oneOf'), indent=2, ensure_ascii=False)[:300])
print('to:', obj.get('to'))
print('cc:', obj.get('cc'))
"

elif [ "$1" = "clear-pending" ]; then
  docker compose exec api python3 -c "
from app.models import PendingDelivery, get_session
with get_session() as s:
    n = s.query(PendingDelivery).delete()
    s.commit()
    print(f'cleared {n} pending deliveries')
"

elif [ "$1" = "clear-follow" ]; then
  docker compose exec api python3 -c "
from app.models import Follow, User, ProcessedActivity, get_session
with get_session() as s:
    local = s.query(User).filter_by(username='siarte', is_remote=False).first()
    remote = s.query(User).filter_by(username='siarte@daydream.ink').first()
    f = s.query(Follow).filter_by(follower_id=local.id, following_id=remote.id).first()
    if f: s.delete(f)
    s.query(ProcessedActivity).delete()
    s.commit()
    print('cleared')
"

elif [ "$1" = "check-pending" ]; then
  docker compose exec api python3 -c "
from app.models import Follow, User, get_session
with get_session() as s:
    local = s.query(User).filter_by(username='siarte', is_remote=False).first()
    remote = s.query(User).filter_by(username='siarte@daydream.ink').first()
    if not local or not remote: print('users not found'); exit()
    f = s.query(Follow).filter_by(follower_id=local.id, following_id=remote.id).first()
    print('follow exists:', f is not None)
    if f: print('accepted:', f.accepted)
"

elif [ "$1" = "check-remote" ]; then
  docker compose exec api python3 -c "
from app.models import User, get_session
with get_session() as s:
    u = s.query(User).filter(User.username.like('%@%')).first()
    if u:
        print('username:', u.username)
        print('inbox_url:', u.inbox_url)
        print('remote_url:', u.remote_url)
        print('actor_uri:', u.actor_uri())
        print('shared_inbox:', u.shared_inbox_url)
    else:
        print('no remote users')
"

elif [ "$1" = "check-follow" ]; then
  docker compose exec api python3 -c "
from app.models import Follow, User, get_session
with get_session() as s:
    u = s.query(User).filter_by(username='siarte').first()
    if not u: print('user not found'); exit()
    follows = s.query(Follow).filter_by(following_id=u.id).all()
    if not follows: print('no follows'); exit()
    for f in follows:
        follower = s.query(User).get(f.follower_id)
        print(f'follower: {follower.username} ({follower.id}) accepted={f.accepted}')
"

elif [ "$1" = "check-baseurl" ]; then
  docker compose exec api python3 -c "
from app.config import BASE_URL, SCHEME, DOMAIN
print('BASE_URL:', BASE_URL)
print('SCHEME:', SCHEME)
print('DOMAIN:', DOMAIN)
"

elif [ "$1" = "check-mention" ]; then
  docker compose exec api python3 -c "
import httpx, json, re
url = 'https://writ.daydream.ink/@siarte/3bcfe670'
if len('$2') > 1: url = 'https://writ.daydream.ink/@siarte/' + '$2'
r = httpx.get(url, headers={'Accept': 'application/activity+json'})
if r.status_code == 200:
    d = r.json()
    obj = d.get('object', d)
    print('=== 멘션 tag ===')
    print(json.dumps(obj.get('tag', []), indent=2, ensure_ascii=False)[:500])
    print('to:', obj.get('to'), 'cc:', obj.get('cc'))
    print('--- content <a> 태그 ---')
    for m in re.finditer(r'<a[^>]*class=\"u-url mention\"[^>]*>.*?</a>', obj.get('content','')):
        print(m.group()[:300])
else:
    print('status:', r.status_code, r.text[:200])
"

elif [ "$1" = "check-code" ]; then
  docker compose exec api python3 -c "
import sys; sys.path.insert(0,'.'); from app.main import app
import inspect; src = inspect.getsource(app.routes[3].endpoint)
print('ok' if 'Reject' in src else 'FAIL: rebuild needed')
"

elif [ "$1" = "post-test" ]; then
  docker compose exec web node -e "
const http = require('http');
const opts = {hostname:'localhost', port:3000, path:'/@siarte/3bcfe670', headers:{'Accept':'application/activity+json'}};
http.get(opts, res => {
  let body = '';
  res.on('data', c => body += c);
  res.on('end', () => console.log('status:', res.statusCode, 'type:', res.headers['content-type'], 'body:', body.slice(0,200)));
});
"

elif [ "$1" = "api-direct" ]; then
  docker compose exec api python3 -c "
import httpx
r = httpx.get('http://localhost:8000/api/by-number/siarte/3bcfe670', headers={'Accept': 'application/activity+json'})
print('status:', r.status_code)
if r.status_code == 200:
    d = r.json()
    print('id:', d.get('id'))
    print('type:', d.get('type'))
"

elif [ "$1" = "api-test" ]; then
  docker compose exec web node -e "
const http = require('http');
const data = JSON.stringify({test:true});
const req = http.request('http://api:8000/users/siarte/inbox', {
  method: 'POST',
  headers: {'Content-Type': 'application/activity+json', 'Content-Length': Buffer.byteLength(data)}
}, (res) => {
  let body = '';
  res.on('data', chunk => body += chunk);
  res.on('end', () => console.log('status:', res.statusCode, 'body:', body.slice(0,200)));
});
req.write(data);
req.end();
"

elif [ "$1" = "nginx-check" ]; then
  echo "=== nginx 접속 로그 (최근 10줄) ==="
  ls -la /var/log/nginx/*.access.log 2>/dev/null && tail -10 /var/log/nginx/*.access.log 2>/dev/null || echo "로그 파일 없음"
  echo ""
  echo "=== nginx 설정에서 /users/ 처리 확인 ==="
  grep -rn "users\|proxy_pass\|inbox\|location" /etc/nginx/ 2>/dev/null | head -20
  echo ""
  echo "=== curl 로 인박스 테스트 ==="
  curl -s -o /dev/null -w "인박스 POST -> %{http_code}\n" -X POST "https://writ.daydream.ink/users/siarte/inbox" -H "Content-Type: application/activity+json" -d '{"test":true}'
  curl -s -o /dev/null -w "actor GET -> %{http_code}\n" -H "Accept: application/activity+json" "https://writ.daydream.ink/users/siarte"

elif [ "$1" = "mastodon-test" ]; then
  echo "⚠️  daydream.ink 서버에서 docker compose exec web 로 실행:"
  echo ""
  echo "# 1. HTTP 연결 테스트"
  echo 'docker compose exec web curl -s -o /dev/null -w "%{http_code}" -H "Accept: application/activity+json" https://writ.daydream.ink/users/siarte'
  echo ""
  echo "# 2. DNS + SSL + HTTP 한 번에"
  echo 'docker compose exec web python3 -c "'
  echo 'import socket, ssl, http.client'
  echo 'try:'
  echo '    ip = socket.getaddrinfo(\"writ.daydream.ink\", 443)'
  echo '    print(\"DNS OK:\", ip[0][4][0])'
  echo '    ctx = ssl.create_default_context()'
  echo '    conn = http.client.HTTPSConnection(\"writ.daydream.ink\", 443, context=ctx, timeout=5)'
  echo '    conn.request(\"GET\", \"/users/siarte\", headers={\"Accept\": \"application/activity+json\"})'
  echo '    r = conn.getresponse()'
  echo '    print(\"HTTP:\", r.status)'
  echo '    conn.close()'
  echo 'except Exception as e:'
  echo '    print(\"FAIL:\", e)'
  echo '"'

elif [ "$1" = "webfinger-test" ]; then
  docker compose exec api python3 -c "
import httpx
r = httpx.get('https://writ.daydream.ink/.well-known/webfinger?resource=acct:siarte@writ.daydream.ink')
print('WebFinger:', r.status_code)
if r.status_code != 200: print(r.text[:300]); exit()
data = r.json()
for link in data.get('links', []):
    if link.get('type') == 'application/activity+json':
        actor_url = link['href']
        print('Actor URL:', actor_url)
        r2 = httpx.get(actor_url, headers={'Accept': 'application/activity+json'})
        print('Actor fetch:', r2.status_code)
        if r2.status_code == 200:
            print('type:', r2.json().get('type'))
            print('pubkey len:', len(r2.json().get('publicKey',{}).get('publicKeyPem','')))
        else:
            print('body:', r2.text[:200])
        break
"

elif [ "$1" = "direct-fetch" ]; then
  docker compose exec api python3 -c "
import sys, traceback
sys.path.insert(0, '.')
from app.routes.api import _ap_fetch, _fetch_and_save_ap_object
from app.models import User, get_session

url = 'https://daydream.ink/@siarte/116895178885643677'
with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()

# _ap_fetch로 데이터 가져오기
try:
    data = _ap_fetch(url, me)
    if not data:
        print('_ap_fetch returned None')
    else:
        obj = data.get('object', data)
        print('_ap_fetch success, obj type:', obj.get('type'))
        print('content exists:', bool(obj.get('content', '')))
        print('attributedTo:', obj.get('attributedTo', 'N/A')[:80])
        
        # 저장 시도
        result = _fetch_and_save_ap_object(obj, me)
        print('save result:', result is not None)
except Exception as e:
    traceback.print_exc()
"

elif [ "$1" = "network-check" ]; then
  docker compose exec api python3 -c "
import httpx
for target in ['https://daydream.ink', 'https://writ.daydream.ink', 'https://mylittle.boutique']:
    try:
        r = httpx.get(target, timeout=5)
        print(f'{target} -> {r.status_code} ({len(r.content)} bytes)')
    except Exception as e:
        print(f'{target} -> FAIL: {e}')
"

else
  echo "사용법: ./gogo.sh [명령어]"
  echo ""
  echo "명령어:"
  echo "  fetch-log     - API 로그 확인"
  echo "  rebuild       - 코드 풀 + api 빌드 + 재시작"
  echo "  exec          - 외부 URL 요청 테스트 (path 확인)"
  echo "  key-test      - 서명/키 검증"
  echo "  network-check - 네트워크 연결 확인"
  echo "  api-test      - API 인박스 직접 테스트"
fi
