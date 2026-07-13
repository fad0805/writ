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

elif [ "$1" = "planet-poll" ]; then
  docker compose exec api python3 -c "
import httpx, json
r = httpx.get('https://planet.moe/@siarte/116901379728907920', headers={'Accept':'application/activity+json'})
if r.status_code == 200:
    d = r.json()
    obj = d.get('object', d)
    print('type:', obj.get('type'))
    print('options:', json.dumps(obj.get('oneOf'), indent=2, ensure_ascii=False)[:500])
    print('to:', obj.get('to'))
    print('cc:', obj.get('cc'))
else:
    print(r.status_code, r.text[:200])
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

elif [ "$1" = "check-thread" ]; then
  docker compose exec api python3 -c "
from app.models import Post, get_session
with get_session() as s:
    p = s.query(Post).filter(Post.ap_id.like('%116901658252254236')).first()
    if p:
        print('found:', p.id, p.number, 'in_reply_to:', p.in_reply_to_ap_id)
        # Also check replies
        replies = s.query(Post).filter(Post.in_reply_to_ap_id == p.ap_id).all()
        print('replies count:', len(replies))
        for r in replies:
            print('  reply:', r.id, r.ap_id[:80])
    else:
        print('not found in DB')
"

elif [ "$1" = "check-db" ]; then
  docker compose exec api python3 -c "
from app.models import Post, Vote, get_session
with get_session() as s:
    p = s.query(Post).filter(Post.poll_data.isnot(None)).order_by(Post.id.desc()).first()
    if p:
        print('number:', p.number, 'ap_id:', p.ap_id)
        print('poll_data:', p.poll_data)
        votes = s.query(Vote).filter_by(post_id=p.id).all()
        print('votes:', [(v.user_id, v.option_index) for v in votes])
    else:
        print('no polls found')
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

elif [ "$1" = "clear-notifs" ]; then
  docker compose exec api python3 -c "
from app.models import Notification, Post, get_session
with get_session() as s:
    deleted = 0
    for n in s.query(Notification).filter(Notification.post_id.isnot(None)).all():
        p = s.query(Post).get(n.post_id)
        if p and p.is_deleted:
            s.delete(n)
            deleted += 1
    s.commit()
    print(f'deleted {deleted} notifications for deleted posts')
"

elif [ "$1" = "check-custom-fields" ]; then
  actor_url="${2}"
  if [ -z "$actor_url" ]; then
    echo "사용법: ./gogo.sh check-custom-fields [actor_url]" >&2
    echo "예시: ./gogo.sh check-custom-fields https://daydream.ink/users/siarte" >&2
    exit 1
  fi
  docker compose exec -T -e ACTOR_URL="$actor_url" api python3 << 'PYEOF'
import os, json, httpx, re, sys

url = os.environ["ACTOR_URL"]
r = httpx.get(url, headers={"Accept": "application/activity+json"}, timeout=10)
if r.status_code != 200:
    print(f"fetch failed: {r.status_code} {r.text[:200]}")
    sys.exit(1)

data = r.json()
print("=== Actor Info ===")
print(f"type: {data.get('type')}")
print(f"preferredUsername: {data.get('preferredUsername')}")
print(f"name: {data.get('name')}")

print("\n=== Attachment (custom fields) ===")
attachment = data.get("attachment", [])
print(f"count: {len(attachment)}")
for i, item in enumerate(attachment):
    print(f"\n--- field {i} ---")
    print(f"  type: {item.get('type')}")
    print(f"  name: {item.get('name')}")
    print(f"  value: {item.get('value')[:200] if item.get('value') else ''}")

print("\n=== Processed by _extract_custom_fields ===")
from app.activitypub import _extract_custom_fields
fields = _extract_custom_fields(attachment)
print(json.dumps(fields, indent=2, ensure_ascii=False))

# Also show the raw attachment JSON
print(f"\n=== Raw attachment JSON ===")
print(json.dumps(attachment, indent=2, ensure_ascii=False)[:2000])
PYEOF

elif [ "$1" = "fix-follow" ]; then
  local_name="${2:-siarte}"
  remote_handle="${3:-}"
  if [ -z "$remote_handle" ]; then
    echo "사용법: ./gogo.sh fix-follow [로컬유저] [원격핸들]" >&2
    echo "예시: ./gogo.sh fix-follow siarte alex@daydream.ink" >&2
    exit 1
  fi
  docker compose exec -T -e LOCAL_USER="$local_name" -e REMOTE_HANDLE="$remote_handle" api python3 << 'PYEOF'
import os, json, time
from app.models import Follow, User, get_session
from app.activitypub import _post_to_inbox
from app.config import BASE_URL

local_name = os.environ["LOCAL_USER"]
remote_handle = os.environ["REMOTE_HANDLE"]

with get_session() as s:
    me = s.query(User).filter_by(username=local_name, is_remote=False).first()
    if not me:
        print(f"local user '{local_name}' not found")
        exit(1)
    remote = s.query(User).filter_by(username=remote_handle, is_remote=True).first()
    if not remote:
        # try partial match on remote_url
        domain = remote_handle.split("@")[-1] if "@" in remote_handle else None
        if domain:
            remote = s.query(User).filter(User.remote_url.contains(domain)).first()
    if not remote:
        print(f"remote user '{remote_handle}' not found")
        print("remote users in DB:")
        for u in s.query(User).filter(User.is_remote == True).all():
            print(f"  {u.username} ({u.remote_url})")
        exit(1)

    follow = s.query(Follow).filter_by(follower_id=remote.id, following_id=me.id).first()
    if not follow:
        print(f"no follow record: {remote_handle}->{local_name}")
        follow2 = s.query(Follow).filter_by(follower_id=me.id, following_id=remote.id).first()
        if follow2:
            print(f"  reverse follow exists (local->remote): accepted={follow2.accepted}")
        exit(1)

    was = follow.accepted
    if was:
        print("already accepted=True")
    else:
        follow.accepted = True
        s.commit()
        print(f"accepted: {was} -> True")

    inbox = remote.inbox_url or remote.shared_inbox_url or (remote.actor_uri().rstrip("/") + "/inbox")
    print(f"follower: {remote.username} inbox: {inbox}")

    activity_id = follow.activity_id or f"{remote.actor_uri()}/follows/{follow.id}"
    follow_obj = {"id": activity_id, "type": "Follow", "actor": remote.actor_uri(), "object": me.actor_uri()}
    accept = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{BASE_URL}/activities/accept/{follow.id}-{int(time.time())}",
        "type": "Accept",
        "actor": me.actor_uri(),
        "object": follow_obj,
    }
    print(f"sending Accept to {inbox} ...")
    try:
        _post_to_inbox(inbox, accept, me)
        print("done")
    except Exception as e:
        print(f"send failed: {e}")
PYEOF
elif [ "$1" = "flag-test-signed" ]; then
  docker compose exec -T api python3 << 'PYEOF'
import httpx, json, time, datetime, hashlib, base64
from app.crypto_utils import sign_string, get_private_key, verify_signature
from app.models import User, get_session
from app.config import SECRET_KEY, DOMAIN
from urllib.parse import urlparse

flag = {"@context":"https://www.w3.org/ns/activitystreams","id":"https://test.local/flag/1","type":"Flag","actor":"https://writ.daydream.ink/users/siarte","object":["https://writ.daydream.ink/users/siarte"],"content":"test"}
body = json.dumps(flag, ensure_ascii=False).encode()
url = "http://localhost:8000/inbox"
with get_session() as s:
    me = s.query(User).filter_by(username="siarte").first()
    priv = get_private_key(me, SECRET_KEY)
    parsed = urlparse(url)
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    created = int(time.time())
    # sign with public hostname, not localhost
    ss = f"(request-target): post {parsed.path}\nhost: {DOMAIN}\ndate: {date}\ndigest: SHA-256={digest}\n(created): {created}"
    sig = sign_string(ss, priv)
    sig_header = f'keyId="{me.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date digest (created)",signature="{sig}"'
    headers = {"Content-Type":"application/activity+json","Signature":sig_header,"Date":date,"Digest":f"SHA-256={digest}","Host":DOMAIN}
    
    print("=== DEBUG ===")
    print("keyId:", me.actor_uri() + "#main-key")
    print("actor:", me.actor_uri())
    print("signed_string:", repr(ss))
    print("self-verify:", verify_signature(ss, sig, me.public_key))
    
    r = httpx.post(url, content=body, headers=headers, timeout=10)
    print("status:", r.status_code, "body:", r.text[:200])
PYEOF

elif [ "$1" = "whitelist-add" ]; then
  domain="${2:-daydream.ink}"
  docker compose exec -T api python3 -c "
from app.models import AllowedServer, get_session
with get_session() as s:
    exists = s.query(AllowedServer).filter_by(domain='$domain').first()
    if exists:
        print('$domain already in whitelist')
    else:
        s.add(AllowedServer(domain='$domain'))
        s.commit()
        print('added $domain to whitelist')
"

elif [ "$1" = "test-api-direct" ]; then
  docker compose exec api python3 -c "
import httpx
r = httpx.post('http://localhost:8000/users/siarte/inbox',
  json={'type':'Flag','actor':'https://daydream.ink/actor','object':['https://writ.daydream.ink/users/siarte']})
print('status:', r.status_code, 'body:', r.text[:200])
"

elif [ "$1" = "test-web-proxy" ]; then
  docker compose exec web python3 -c "
import httpx
r = httpx.post('http://localhost:3000/users/siarte/inbox',
  json={'type':'Flag','actor':'https://daydream.ink/actor','object':['https://writ.daydream.ink/users/siarte']})
print('status:', r.status_code, 'body:', r.text[:200])
"

elif [ "$1" = "check-notifs" ]; then
  docker compose exec api python3 -c "
from app.models import Notification, get_session
with get_session() as s:
    notifs = s.query(Notification).order_by(Notification.created_at.desc()).limit(5).all()
    if not notifs:
        print('no notifications found')
    for n in notifs:
        print(f'  #{n.id} type={n.notification_type} user={n.user_id} from={n.from_user_id} meta={n.metadata_json[:100] if n.metadata_json else \"\"}')
"

elif [ "$1" = "check-reports" ]; then
  docker compose exec api python3 -c "
from app.models import Report, get_session
with get_session() as s:
    reports = s.query(Report).order_by(Report.created_at.desc()).limit(10).all()
    if not reports:
        print('no reports found')
    for r in reports:
        print(f'  #{r.id} type={r.target_type} id={r.target_id} reporter={r.reporter_id} status={r.status} reason={r.reason[:50]}')
"

elif [ "$1" = "check-actor" ]; then
  actor_url="${2:-https://daydream.ink/actor}"
  docker compose exec api python3 -c "
import httpx
url = '$actor_url'
r = httpx.get(url, headers={'Accept': 'application/activity+json'}, timeout=10)
print('status:', r.status_code)
if r.status_code == 200:
    d = r.json()
    print('type:', d.get('type'))
    print('preferredUsername:', d.get('preferredUsername'))
    pubkey = d.get('publicKey', {}).get('publicKeyPem', '')[:80] if isinstance(d.get('publicKey'), dict) else 'N/A'
    print('publicKey:', pubkey + '...')
    print('inbox:', d.get('inbox'))
else:
    print('body:', r.text[:300])
"

elif [ "$1" = "check-outbox" ]; then
  id="${2:-7c930c98}"
  docker compose exec api python3 -c "
import httpx, json, re
url = 'https://writ.daydream.ink/@siarte/$id'
r = httpx.get(url, headers={'Accept': 'application/activity+json'})
d = r.json()
obj = d.get('object', d)
print('=== OUTBOX ===')
print('type:', obj.get('type'))
print('content:', obj.get('content','')[:400])
print('tag:', json.dumps(obj.get('tag',[]), indent=2, ensure_ascii=False)[:300])
print('to:', obj.get('to'))
print('cc:', obj.get('cc'))
print()
for m in re.finditer(r'<a[^>]*>', obj.get('content','')):
    print('link:', m.group()[:200])
"

elif [ "$1" = "flag-test" ]; then
  inbox_url="${2:-https://writ.daydream.ink/inbox}"
  docker compose exec api python3 -c "
import httpx, json, sys
from app.crypto_utils import sign_string, get_private_key
from app.models import User, get_session
from app.config import SECRET_KEY
from urllib.parse import urlparse

flag = {
    '@context': 'https://www.w3.org/ns/activitystreams',
    'id': 'https://test.local/flag/1',
    'type': 'Flag',
    'actor': 'https://writ.daydream.ink/users/siarte',
    'object': ['https://writ.daydream.ink/users/siarte'],
    'content': 'test report',
}
body = json.dumps(flag, ensure_ascii=False).encode()
inbox_url = '$inbox_url'
with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()
    priv = get_private_key(me, SECRET_KEY)
    import datetime, time, hashlib, base64
    parsed = urlparse(inbox_url)
    date = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    created = int(time.time())
    ss = f'(request-target): post {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\ndigest: SHA-256={digest}\n(created): {created}'
    sig = sign_string(ss, priv)
    sig_header = f'keyId=\"{me.actor_uri()}#main-key\",algorithm=\"hs2019\",created=\"{created}\",headers=\"(request-target) host date digest (created)\",signature=\"{sig}\"'
    headers = {
        'Content-Type': 'application/activity+json',
        'Signature': sig_header,
        'Date': date,
        'Digest': f'SHA-256={digest}',
        'Host': parsed.netloc,
    }
    r = httpx.post(inbox_url, content=body, headers=headers, timeout=10)
    print('inbox:', inbox_url)
    print('status:', r.status_code)
    print('body:', r.text[:200])
"

elif [ "$1" = "check-inbox" ]; then
  docker compose exec api python3 -c "
import httpx
# 루트 인박스로 테스트 Flag 발송
from app.models import User, Report, get_session
from app.config import BASE_URL
flag = {
    '@context': 'https://www.w3.org/ns/activitystreams',
    'type': 'Flag',
    'actor': 'https://writ.daydream.ink/users/siarte',
    'object': ['https://daydream.ink/users/someuser'],
    'content': 'Test report from gogo.sh',
}
r = httpx.post(f'{BASE_URL}/inbox', json=flag, headers={'Content-Type': 'application/activity+json'})
print('status:', r.status_code)
print('body:', r.text[:200])
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

elif [ "$1" = "check-emoji-domains" ]; then
  docker compose exec api python3 -c "
from app.models import CustomEmoji, get_session
with get_session() as s:
    emojis = s.query(CustomEmoji).all()
    local_count = 0
    remote_count = 0
    for e in emojis:
        sub = 'remote' if e.domain else 'local'
        if sub == 'local': local_count += 1
        else: remote_count += 1
        print(f'  keyword={e.keyword}  domain=\"{e.domain}\"  -> {sub}/{e.file_name}')
    print(f'total: {len(emojis)} (local={local_count}, remote={remote_count})')
"

elif [ "$1" = "migrate-emojis" ]; then
  docker compose exec api python3 -c "
import os, shutil
from app.models import CustomEmoji, get_session
from app.config import S3_ENABLED

EMOJI_DIR = '/app/web/public/emojis'
moved = 0
skipped = 0
errors = 0

with get_session() as s:
    emojis = s.query(CustomEmoji).all()
    for e in emojis:
        sub = 'remote' if e.domain else 'local'
        old_key = f'emojis/{e.file_name}'
        new_key = f'emojis/{sub}/{e.file_name}'
        old_path = os.path.join(EMOJI_DIR, e.file_name)
        new_dir = os.path.join(EMOJI_DIR, sub)
        new_path = os.path.join(new_dir, e.file_name)

        if os.path.exists(new_path):
            skipped += 1
            continue

        if S3_ENABLED:
            try:
                from app.utils.storage import get_storage
                storage = get_storage()
                data = storage.read(old_key)
                storage.save(new_key, data, 'image/webp')
                try:
                    storage.delete(old_key)
                except Exception:
                    pass
                moved += 1
                continue
            except Exception:
                pass

        if os.path.exists(old_path):
            os.makedirs(new_dir, exist_ok=True)
            shutil.move(old_path, new_path)
            moved += 1
        else:
            skipped += 1

print(f'done: {moved} moved, {skipped} skipped, {errors} errors (total {len(emojis)} emojis)')
"

else
  echo "사용법: ./gogo.sh [명령어]"
  echo ""
  echo "명령어:"
  echo "  fetch-log       - API 로그 확인"
  echo "  rebuild         - 코드 풀 + api 빌드 + 재시작"
  echo "  exec            - 외부 URL 요청 테스트 (path 확인)"
  echo "  key-test        - 서명/키 검증"
  echo "  network-check   - 네트워크 연결 확인"
  echo "  api-test        - API 인박스 직접 테스트"
  echo "  migrate-emojis  - 이모지 파일 local/remote 경로 마이그레이션"
  echo "  fix-follow      - 꼬인 팔로우 강제 수락 및 Accept 전송 (예: ./gogo.sh fix-follow siarte alex@daydream.ink)"
  echo "  check-custom-fields - 원격 액터의 attachment/custom_fields 확인 (예: ./gogo.sh check-custom-fields https://daydream.ink/users/siarte)"
fi
