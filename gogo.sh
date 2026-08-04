#!/bin/bash
# 실행: bash gogo.sh [명령어]
# 호스트(서버)에서 실행하세요.

if [ "$1" = "fetch-log" ]; then
  docker compose logs api --tail 30

elif [ "$1" = "rebuild" ]; then
  git pull
  BASE_URL=$(grep -E '^BASE_URL=' .env.production 2>/dev/null | head -1 | cut -d= -f2-)
  export BASE_URL
  docker compose build api web
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
from app.models import User
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session

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
from app.models import User
from app.db.database import get_session
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
from app.models import Follow, User
from app.db.database import get_session
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
from app.models import Post
from app.db.database import get_session
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
from app.models import Post, Vote
from app.db.database import get_session
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
from app.models import PendingDelivery
from app.db.database import get_session
with get_session() as s:
    n = s.query(PendingDelivery).delete()
    s.commit()
    print(f'cleared {n} pending deliveries')
"

elif [ "$1" = "clear-follow" ]; then
  docker compose exec api python3 -c "
from app.models import Follow, User, ProcessedActivity
from app.db.database import get_session
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
from app.models import Follow, User
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session
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
from app.models import Follow, User
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session

url = '$2'
with get_session() as s:
    me = s.query(User).filter_by(username='siarte').first()

# _ap_fetch로 데이터 가져오기
try:
    data = _ap_fetch(url, me)
    if not data:
        print('_ap_fetch returned None')
    else:
        obj = data.get('object', data)
        print('obj:', obj)
        print('_ap_fetch success, obj type:', obj.get('type'))
        print('content exists:', bool(obj.get('content', '')))
        print('attributedTo:', obj.get('attributedTo', 'N/A')[:80])
        # 저장 시도
        result = _fetch_and_save_ap_object(obj, me)
        print('save result:', result is not None)
except Exception as e:
    traceback.print_exc()
"

elif [ "$1" = "purge-deleted" ]; then
  docker compose exec -T api python3 <<'PYEOF'
from app.models import Post, Like, Boost, Bookmark, Vote, Notification
from app.db.database import get_session

def _hard_delete(s, pid):
    s.query(Like).filter(Like.post_id == pid).delete()
    s.query(Boost).filter(Boost.post_id == pid).delete()
    s.query(Bookmark).filter(Bookmark.post_id == pid).delete()
    s.query(Vote).filter(Vote.post_id == pid).delete()
    s.query(Notification).filter(Notification.post_id == pid).delete()
    p = s.query(Post).get(pid)
    if p:
        s.delete(p)

def _all_descendants_deleted(s, pid):
    """Check if every post in the reply subtree of pid is deleted or nonexistent."""
    children = s.query(Post).filter(Post.in_reply_to_id == pid).all()
    for c in children:
        if not c.is_deleted:
            return False
        if not _all_descendants_deleted(s, c.id):
            return False
    return True

with get_session() as s:
    # Pass 1: purge leaf deleted posts, keep shells for thread parents
    deleted = s.query(Post).filter(Post.is_deleted == True).all()
    total = len(deleted)
    purged = 0
    kept = 0
    for p in deleted:
        has_replies = s.query(Post).filter(Post.in_reply_to_id == p.id).first() is not None
        if not has_replies and p.ap_id:
            has_replies = s.query(Post).filter(Post.in_reply_to_ap_id == p.ap_id).first() is not None
        if has_replies:
            kept += 1
            if p.content:
                p.content = ""
                p.media_attachments = []
                p.poll_data = None
                p.link_preview = None
            continue
        _hard_delete(s, p.id)
        purged += 1
    s.commit()
    print(f"pass 1: purged {purged} leaf, kept {kept} shell")

    # Pass 2: recursively purge shells whose entire subtree is also deleted
    kept = s.query(Post).filter(Post.is_deleted == True).all()
    pass2 = 0
    for p in kept:
        if _all_descendants_deleted(s, p.id):
            _hard_delete(s, p.id)
            pass2 += 1
    s.commit()
    print(f"pass 2: purged {pass2} shells (whole thread deleted)")

    kept_remaining = s.query(Post).filter(Post.is_deleted == True).count()
    print(f"remaining shells: {kept_remaining}")
PYEOF

elif [ "$1" = "clear-notifs" ]; then
  docker compose exec api python3 -c "
from app.models import Notification, Post
from app.db.database import get_session
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

elif [ "$1" = "refresh-actor" ]; then
  actor_url="${2}"
  if [ -z "$actor_url" ]; then
    echo "사용법: ./gogo.sh refresh-actor [actor_url]" >&2
    echo "예시: ./gogo.sh refresh-actor https://misskey.io/users/xxx" >&2
    exit 1
  fi
  docker compose exec -T -e ACTOR_URL="$actor_url" api python3 <<'PYEOF'
import os, httpx
from app.activitypub import _resolve_actor, _process_emoji_tags
from app.models import User
from app.db.database import get_session

url = os.environ["ACTOR_URL"]
# First check if user exists
with get_session() as s:
    u = s.query(User).filter_by(remote_url=url).first()
    if not u:
        u = s.query(User).filter(User.remote_url.contains(url.split("/")[-1])).first()
    if u:
        print(f"found: username={u.username} remote_url={u.remote_url}")
    else:
        print("user not in DB, will try to resolve")

# Force refresh
from app.config import SECRET_KEY
from app.crypto_utils import get_private_key
sign_as = None
with get_session() as s:
    sign_as = s.query(User).filter_by(is_remote=False).first()

actor = _resolve_actor(url, force_refresh=True, sign_as=sign_as)
if actor:
    print(f"resolved: id={actor.id} username={actor.username}")
    print(f"display_name={actor.display_name}")
    print(f"summary={actor.summary[:100] if actor.summary else ''}")
    print(f"avatar={actor.profile_image}")
    print(f"inbox={actor.inbox_url}")
    print(f"remote_url={actor.remote_url}")
else:
    print("resolve failed")
PYEOF

elif [ "$1" = "dedup-users" ]; then
  docker compose exec -T api python3 <<'PYEOF'
import re
from app.models import User, Follow, Post, Like, Boost, Bookmark, Vote, Notification, UserBlock, UserMute
from app.db.database import get_session

def _merge(s, keep, dup):
    print(f"  KEEP id={keep.id} ({keep.username})  MERGE id={dup.id} ({dup.username})")
    for table, fk in [(Follow, "follower_id"), (Follow, "following_id"),
                      (Post, "author_id"), (Like, "user_id"), (Boost, "user_id"),
                      (Bookmark, "user_id"), (Vote, "user_id"),
                      (Notification, "user_id"), (Notification, "from_user_id"),
                      (UserBlock, "user_id"), (UserBlock, "target_user_id"),
                      (UserMute, "user_id"), (UserMute, "target_user_id")]:
        try:
            s.query(table).filter_by(**{fk: dup.id}).update({fk: keep.id})
        except Exception:
            pass
    s.delete(dup)

with get_session() as s:
    all_remote = s.query(User).filter(User.is_remote == True).order_by(User.id).all()
    groups = {}
    for u in all_remote:
        local = u.username.split("@")[0]
        domain = ""
        if u.remote_url:
            m = re.search(r'https?://([^/]+)', u.remote_url)
            if m:
                domain = m.group(1)
        key = f"{local}@{domain}" if domain else local
        groups.setdefault(key, []).append(u)

    total = 0
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        print(f"\n=== {key} ({len(group)} users) ===")
        group.sort(key=lambda x: (len(x.remote_url or ""), x.id))
        keep = group[0]
        for dup in group[1:]:
            _merge(s, keep, dup)
            total += 1
    s.commit()
    print(f"\ntotal merged: {total}")
    if total == 0:
        print("no duplicates found")
PYEOF

elif [ "$1" = "purge-orphan" ]; then
  docker compose exec -T api python3 <<'PYEOF'
from app.models import Post, Notification, Like, Boost, Bookmark, Vote
from app.db.database import get_session

with get_session() as s:
    orphans = s.query(Post).filter(
        Post.content.is_(None) | (Post.content == ""),
        Post.boost_of_id.is_(None),
        Post.in_reply_to_id.is_(None),
        (Post.in_reply_to_ap_id == "") | Post.in_reply_to_ap_id.is_(None),
        Post.ap_id.is_(None),
        Post.is_deleted == False,
    ).all()
    if not orphans:
        print("no orphan posts found")
    else:
        deleted = 0
        for p in orphans:
            s.query(Notification).filter(Notification.post_id == p.id).delete()
            s.query(Like).filter(Like.post_id == p.id).delete()
            s.query(Boost).filter(Boost.post_id == p.id).delete()
            s.query(Bookmark).filter(Bookmark.post_id == p.id).delete()
            s.query(Vote).filter(Vote.post_id == p.id).delete()
            s.delete(p)
            deleted += 1
        s.commit()
        print(f"deleted {deleted} orphan posts")
PYEOF

elif [ "$1" = "check-post" ]; then
  post_id="${2}"
  if [ -z "$post_id" ]; then
    echo "사용법: ./gogo.sh check-post [post_id]" >&2
    exit 1
  fi
  docker compose exec -T api python3 <<PYEOF
import json, sys
from app.models import Post, User
from app.db.database import get_session

with get_session() as s:
    try:
        p = s.query(Post).get(int($post_id))
    except ValueError:
        p = s.query(Post).filter(Post.ap_id == "$post_id").first()
    if not p:
        print("post not found")
        sys.exit(1)
    print(f"id={p.id} number={p.number} author_id={p.author_id} is_deleted={p.is_deleted}")
    print(f"content={p.content[:100] if p.content else ''}")
    print(f"visibility={p.visibility} is_dm={p.is_dm}")
    print(f"boost_of_id={p.boost_of_id}")
    print(f"ap_id={p.ap_id}")
    print(f"in_reply_to_id={p.in_reply_to_id}")
    print(f"in_reply_to_ap_id={p.in_reply_to_ap_id}")
    print(f"mentioned_user_ids={p.mentioned_user_ids}")
    print(f"created_at={p.created_at}")
    print(f"bumped_at={p.bumped_at}")
    author = s.query(User).get(p.author_id)
    print(f"author_username={author.username if author else '?'} (is_remote={author.is_remote if author else '?'})")
    if p.in_reply_to_id:
        parent = s.query(Post).get(p.in_reply_to_id)
        if parent:
            pauthor = s.query(User).get(parent.author_id)
            print(f"\n--- parent post {parent.id} ---")
            print(f"author_id={parent.author_id} author_username={pauthor.username if pauthor else '?'}")
            print(f"content={parent.content[:100] if parent.content else ''}")
            print(f"visibility={parent.visibility} is_deleted={parent.is_deleted}")
            print(f"ap_id={parent.ap_id}")
        else:
            print(f"\nparent post {p.in_reply_to_id}: not found in DB")
    if p.in_reply_to_ap_id and (not p.in_reply_to_id or not s.query(Post).get(p.in_reply_to_id)):
        print(f"\nremote parent: {p.in_reply_to_ap_id}")
PYEOF

elif [ "$1" = "check-custom-fields" ]; then
  actor_url="${2}"
  if [ -z "$actor_url" ]; then
    echo "사용법: ./gogo.sh check-custom-fields [actor_url]" >&2
    echo "예시: ./gogo.sh check-custom-fields https://daydream.ink/users/siarte" >&2
    exit 1
  fi
  docker compose exec -T -e ACTOR_URL="$actor_url" api python3 <<'PYEOF'
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
  docker compose exec -T -e LOCAL_USER="$local_name" -e REMOTE_HANDLE="$remote_handle" api python3 <<'PYEOF'
import os, json, time
from app.models import Follow, User
from app.db.database import get_session
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
  docker compose exec -T api python3 <<'PYEOF'
import httpx, json, time, datetime, hashlib, base64
from app.crypto_utils import sign_string, get_private_key, verify_signature
from app.models import User
from app.db.database import get_session
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
from app.models import AllowedServer
from app.db.database import get_session
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
from app.models import Notification
from app.db.database import get_session
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
from app.models import User
from app.db.database import get_session
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
from app.models import User, Report
from app.db.database import get_session
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
from app.models import CustomEmoji
from app.db.database import get_session
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
from app.models import CustomEmoji
from app.db.database import get_session
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

elif [ "$1" = "purge-shadows" ]; then
  docker compose exec -T api python3 <<'PYEOF'
from urllib.parse import urlparse
from app.config import BASE_URL
from app.models import User, Follow, Post, Like, Boost, Bookmark, Vote, Notification, UserBlock, UserMute
from app.db.database import get_session

own_domain = urlparse(BASE_URL).hostname or ""
print(f"own domain: {own_domain}")

with get_session() as s:
    shadows = s.query(User).filter(
        User.is_remote == True,
        User.remote_url.like(f"%{own_domain}%"),
    ).all()
    if not shadows:
        print("no shadow users found")
    else:
        deleted = 0
        for u in shadows:
            parsed = urlparse(u.remote_url or "")
            if parsed.hostname and parsed.hostname.lower() == own_domain.lower():
                print(f"  shadow: id={u.id} username={u.username} remote_url={u.remote_url}")
                uid = u.id
                # Delete dependent rows first, one table at a time with rollback on error
                for table, fk in [(Follow, "follower_id"), (Follow, "following_id"),
                                  (Notification, "user_id"), (Notification, "from_user_id"),
                                  (Like, "user_id"), (Boost, "user_id"),
                                  (Bookmark, "user_id"), (Vote, "user_id"),
                                  (UserBlock, "user_id"), (UserBlock, "target_user_id"),
                                  (UserMute, "user_id"), (UserMute, "target_user_id")]:
                    try:
                        n = s.query(table).filter_by(**{fk: uid}).delete()
                        s.commit()
                        if n: print(f"    deleted {n} {table.__name__} rows")
                    except Exception as e:
                        s.rollback()
                        print(f"    skip {table.__name__}: {e}")
                # Nullify FK on Post (author_id) — set to first local user
                try:
                    local_user = s.query(User).filter_by(is_remote=False).first()
                    s.query(Post).filter_by(author_id=uid).update({"author_id": local_user.id if local_user else uid})
                    s.commit()
                except Exception as e:
                    s.rollback()
                    print(f"    skip Post.author_id: {e}")
                # Now delete the user
                try:
                    s.delete(u)
                    s.commit()
                    deleted += 1
                    print(f"    deleted user id={uid}")
                except Exception as e:
                    s.rollback()
                    print(f"    failed to delete user: {e}")
        print(f"deleted {deleted} shadow users")

        # Fix posts with mentioned_user_ids pointing to deleted shadows
        remaining_remote = {u.id for u in s.query(User).filter(User.is_remote == True).all()}
        fixed = 0
        for p in s.query(Post).filter(Post.mentioned_user_ids.isnot(None)).all():
            if p.mentioned_user_ids:
                final_ids = [mid for mid in p.mentioned_user_ids if mid in remaining_remote]
                if final_ids != p.mentioned_user_ids:
                    p.mentioned_user_ids = final_ids
                    fixed += 1
        s.commit()
        print(f"fixed {fixed} posts with stale mentioned_user_ids")
PYEOF

elif [ "$1" = "check-create" ]; then
  docker compose exec api python3 -c "
from app.models import Post
from app.db.database import get_session
from app.utils.to_ap_serializer import to_ap_create
import json

post_id = int('$2')

with get_session() as s:
    p = s.query(Post).filter(Post.id == post_id).first()

    if not p:
        print('post not found')
    else:
        print(json.dumps(to_ap_create(p), indent=2, ensure_ascii=False))
"

elif [ "$1" = "fix-usernames" ]; then
  docker compose exec -T api python3 <<'PYEOF'
from app.models import User, Follow, Post, Like, Boost, Bookmark, Vote, Notification
from app.db.database import get_session

with get_session() as s:
    fixed = 0
    for u in s.query(User).filter(User.is_remote == True).all():
        if u.username and u.username.count("@") > 1:
            parts = u.username.split("@")
            old = u.username
            new = f"{parts[0]}@{parts[1]}"
            u.username = new
            fixed += 1
            print(f"  #{u.id} {old} -> {new}")
    s.commit()
    print(f"\nfixed {fixed} remote usernames")
    if fixed == 0:
        print("no double-domain usernames found")
PYEOF

elif [ "$1" = "replay-mastodon" ]; then
  # 받은 Mastodon Create를 거의 그대로 다시 보내기 (_mention만 WRIT 로컬 유저로)
  # 사용법: ./gogo.sh replay-mastodon <post_id> <target_inbox_url>
  # 예: ./gogo.sh replay-mastodon 5371 https://qdon.space/inbox
  docker compose exec api python3 -c "
import json, datetime, hashlib, base64, httpx
from urllib.parse import urlparse
from app.models import Post, User
from app.db.database import get_session
from app.utils.to_ap_serializer import to_ap_note
from app.config import SECRET_KEY, BASE_URL
from app.crypto_utils import sign_string, get_private_key

post_id = int('$2')
inbox_url = '$3'

with get_session() as s:
    p = s.query(Post).filter(Post.id == post_id).first()
    if not p:
        print('post not found'); exit(1)
    author = p.author

    # 1. to_ap_note() 로 현재 WRIT 포맷 가져오기
    note = to_ap_note(p)

    # 2. Mastodon 포맷으로 최소한의 차이만 적용
    #    - <p> 래핑 제거 (Mastodon은 짧은 글에 <p> 없음)
    content = note.get('content', '')
    if content.startswith('<p>') and content.endswith('</p>'):
        inner = content[3:-4]
        if '<p>' not in inner:
            content = inner
    note['content'] = content

    #    - mediaType 제거 (Mastodon은 보통 없음)
    note.pop('mediaType', None)

    #    - @context 최소화 (Mastodon 표준)
    note['@context'] = 'https://www.w3.org/ns/activitystreams'

    # 3. Create 래퍼 생성 (Mastodon 포맷: to/cc를 Note에서 그대로 사용)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    activity = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'id': f'{BASE_URL}/activities/replay/{p.id}',
        'type': 'Create',
        'actor': author.actor_uri(),
        'published': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'to': note.get('to', []),
        'cc': note.get('cc', []),
        'object': note,
    }

    print('=== REPLAY ACTIVITY ===')
    print(json.dumps(activity, indent=2, ensure_ascii=False))
    print()

    # 4. 서명 후 전송
    body = json.dumps(activity, ensure_ascii=True, sort_keys=True).encode('utf-8')
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    digest_header = f'SHA-256={digest}'
    date = now.strftime('%a, %d %b %Y %H:%M:%S GMT')

    parsed = urlparse(inbox_url)
    path = parsed.path or '/'
    signed_string = (
        f'(request-target): post {path}\n'
        f'host: {parsed.netloc}\n'
        f'date: {date}\n'
        f'digest: {digest_header}'
    )
    signature = sign_string(signed_string, get_private_key(author, SECRET_KEY))
    signature_header = (
        f'keyId=\"{author.actor_uri()}#main-key\",'
        f'algorithm=\"rsa-sha256\",'
        f'headers=\"(request-target) host date digest\",'
        f'signature=\"{signature}\"'
    )
    headers = {
        'Content-Type': 'application/activity+json',
        'Signature': signature_header,
        'Date': date,
        'Digest': digest_header,
        'Host': parsed.netloc,
    }

    resp = httpx.post(inbox_url, content=body, headers=headers, timeout=15)
    print(f'Status: {resp.status_code}')
    print(f'Body: {resp.text[:500]}')
"

elif [ "$1" = "reprocess-avatars" ]; then
  # 저장된 아바타 이미지들을 정사각형으로 센터크롭
  docker compose exec api python3 -c "
import os
from PIL import Image, ImageOps

def process_avatar(path):
    img = Image.open(path)
    if img.size[0] == img.size[1]:
        print(f'  ✔ 이미 정사각형: {path}')
        return
    w, h = img.size
    img = ImageOps.exif_transpose(img)
    sz = min(img.size)
    img = img.crop(((img.width - sz) // 2, (img.height - sz) // 2, (img.width + sz) // 2, (img.height + sz) // 2))
    img = img.resize((400, 400), Image.LANCZOS)
    if img.mode in ('RGBA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = bg
    img.save(path, quality=100)
    print(f'  ▶ {w}x{h} → 400x400: {path}')

count = 0
for root, dirs, files in os.walk('uploads/avatars'):
    for f in sorted(files):
        path = os.path.join(root, f)
        try:
            process_avatar(path)
            count += 1
        except Exception as e:
            print(f'  ✗ {path}: {e}')
# Also check static/uploads/avatars (legacy path)
for root, dirs, files in os.walk('static/uploads/avatars'):
    for f in sorted(files):
        path = os.path.join(root, f)
        try:
            process_avatar(path)
            count += 1
        except Exception as e:
            print(f'  ✗ {path}: {e}')
if count == 0:
    print('처리할 아바타 파일이 없습니다.')
else:
    print(f'\\n{count}개 파일 처리 완료')
"

elif [ "$1" = "profile-timeline" ]; then
  # 타임라인/알림 응답 병목 프로파일링: 각 단계별 시간 + 쿼리 개수 측정
  # 사용법: ./gogo.sh profile-timeline [username] [tl_type]
  USERNAME="${2:-siarte}"
  TL_TYPE="${3:-home}"
  docker compose exec api python3 -c "
import time, sys
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.db.database import get_session, engine
from app.models import User, Post, Notification
from app.core.feed import _get_feed
from app.serializers import _post_json
from app.routes.api.interactions._common import _generate_poll_end_notifications
from app.core.interactions import _can_view
from sqlalchemy.orm import selectinload

query_log = []
@event.listens_for(Engine, 'before_cursor_execute')
def _log_sql(conn, cursor, statement, parameters, context, executemany):
    query_log.append(statement.split(' FROM ')[-1].split(' WHERE ')[0].strip()[:60] if ' FROM ' in statement else statement[:60])

def t(label, start):
    print(f'  {label}: {time.time()-start:.3f}s')

username = '$USERNAME'
tl = '$TL_TYPE'
with get_session() as s:
    user = s.query(User).filter_by(username=username).first()
    if not user:
        print(f'유저를 찾을 수 없습니다: {username}'); sys.exit(1)
    print(f'프로파일 대상: @{username} (id={user.id}), tl={tl}')

    # ── 1. 타임라인 _get_feed ──
    print(f'\\n== _get_feed({tl}) ================')
    t0 = time.time()
    feed, has_more, emojis = _get_feed(user, tl, s, limit=20, offset=0)
    t('total _get_feed', t0)
    print(f'  posts: {len(feed)}, emojis: {len(emojis)}, 쿼리수: {len(query_log)}')

    # ── 2. 알림 엔드포인트 핵심 경로 ──
    print(f'\\n== notifications ================')
    q0 = len(query_log); t0 = time.time()
    _generate_poll_end_notifications(user.id, s)
    t('_generate_poll_end_notifications', t0)
    q = s.query(Notification).options(
        selectinload(Notification.from_user),
        selectinload(Notification.post).selectinload(Post.author),
    ).filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(21).all()
    t('notif query', t0)
    notifs = q[:20]
    print(f'  알림 개수: {len(notifs)}, 쿼리수: {len(query_log)-q0}')

    # 알림 직렬화 (like 리액션 재조회 + _can_view 포함)
    q0 = len(query_log); t0 = time.time()
    n = 0
    for notif in notifs:
        post = notif.post
        if post and not post.is_deleted and _can_view(post, user, s):
            _post_json(post, s, user, _skip_emojis=True)
            n += 1
    t('notif serialize (like-row + can_view 포함)', t0)
    print(f'  직렬화한 포스트: {n}, 쿼리수: {len(query_log)-q0}')

    # ── 3. 단건 포스트 직렬화 성능 (boost 포함) ──
    print(f'\\n== 단건 _post_json ================')
    latest = s.query(Post).filter(Post.is_deleted == False).order_by(Post.created_at.desc()).limit(3).all()
    for p in latest:
        q0 = len(query_log); t0 = time.time()
        _post_json(p, s, user)
        t(f'post #{p.id} (boost_of={p.boost_of_id})', t0)
        print(f'    쿼리수: {len(query_log)-q0}')

    # ── 4. 전체 요약 ──
    print(f'\\n== 총계 ================')
    print(f'누적 SQL 실행 수: {len(query_log)}')
    print(f'주의: 단건 직렬화의 쿼리수가 20+ 이면 N+1 의심')
"

elif [ "$1" = "check-streams" ]; then
  # SSE 스트림 누적/연결 상태 + web→api 왕복 시간 진단
  docker compose exec api python3 -c "
from app.core import timeline_stream as ts
import time, socket
print(f'타임라인 SSE 스트림 수: {len(ts._streams)}')
print(f'알림 SSE 스트림 수: {len(ts._notif_streams)}')
print(f'포스트 SSE 스트림 수: {len(ts._post_streams)}')
print(f'전체 활성 스트림: {len(ts._streams) + len(ts._notif_streams) + len(ts._post_streams)}')
# 스트림별 상세 (최대 30개)
print()
print('== 타임라인 스트림 상세 (uid/tl) ==')
for sid, info in list(ts._streams.items())[:30]:
    print(f'  sid={sid} uid={info.get("user_id")} tl={info.get("tl_type")}')
print()
print('== 알림 스트림 상세 (uid) ==')
for sid, info in list(ts._notif_streams.items())[:30]:
    print(f'  sid={sid} uid={info.get("user_id")}')
print()
print('== 포스트 스트림 상세 (post_id) ==')
for sid, info in list(ts._post_streams.items())[:30]:
    print(f'  sid={sid} post_id={info.get("post_id")}')
"
  echo ""
  echo "== web → api 내부 왕복 시간 (5회) =="
  docker compose exec -T web node -e "
const t0 = Date.now();
fetch('http://api:8000/api/server-info').then(r => {
  console.log('  web→api: ' + (Date.now()-t0) + 'ms (status ' + r.status + ')');
}).catch(e => { console.log('  web→api 실패: ' + e.message); });
" || echo "  (web 컨테이너에서 node 실행 실패)"
  for i in 2 3 4 5; do
    docker compose exec -T web node -e "
const t0 = Date.now();
fetch('http://api:8000/api/server-info').then(r => {
  console.log('  web→api: ' + (Date.now()-t0) + 'ms (status ' + r.status + ')');
}).catch(e => { console.log('  web→api 실패: ' + e.message); });
"
  done
  echo ""
  echo "== 서버 부하 =="
  uptime
  free -m | head -2
  docker stats --no-stream --format "  {{.Name}}: CPU {{.CPUPerc}} MEM {{.MemUsage}}" 2>/dev/null

elif [ "$1" = "check-lna" ]; then
  # Firefox "이 기기의 다른 앱과 서비스에 접근하려고 합니다"(로컬 네트워크 액세스) 팝업
  # 유발하는 사설 주소(localhost/127.*/192.168.*/10.*/172.16-31.*) URL 진단 (읽기 전용)
  # 사용법: ./gogo.sh check-lna [--resolve]  (--resolve = 호스트명을 DNS로 확인해 사설 IP까지 검사)
  RESOLVE_FLAG="${2:-}"
  docker compose exec -T -e RESOLVE_FLAG="$RESOLVE_FLAG" api python3 <<'PYEOF'
import os, ipaddress, re, socket, sys
from urllib.parse import urlparse
from app.models import Post, User, CustomEmoji, Bookmark
from app.db.database import get_session

resolve = os.environ.get("RESOLVE_FLAG") == "--resolve"
_src_re = re.compile(r'<[^>]+\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_poster_re = re.compile(r'<video[^>]+\bposter=["\']([^"\']+)["\']', re.IGNORECASE)
_PRIVATE_ATTRS = ("is_private", "is_loopback", "is_link_local", "is_reserved")
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".writ")


def _ip_literal(h):
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return any(getattr(ip, a, False) for a in _PRIVATE_ATTRS)


def _resolve_private(h):
    try:
        infos = socket.getaddrinfo(h, None)
    except OSError:
        return False
    return any(_ip_literal(i[4][0]) for i in infos)


def is_private_url(url):
    if not url or not url.startswith("http"):
        return False
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    h = host.strip("[]").lower()
    if h == "localhost" or h.endswith(".localhost") or h in ("0.0.0.0", "::1"):
        return True
    if _ip_literal(h):
        return True
    if h.endswith(_PRIVATE_SUFFIXES):
        return True
    if resolve:
        return _resolve_private(h)
    return False


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)
    elif isinstance(obj, str) and obj.startswith("http"):
        yield obj


def _post_urls(p):
    urls = set()
    if p.content:
        for m in _src_re.finditer(p.content):
            urls.add(m.group(1))
        for m in _poster_re.finditer(p.content):
            urls.add(m.group(1))
    for att in (p.media_attachments or []):
        urls.update(_walk(att))
    if p.link_preview:
        urls.update(_walk(p.link_preview))
    return urls


hits = []
with get_session() as s:
    posts = s.query(Post).filter(Post.is_deleted == False).order_by(Post.id).limit(20000).all()
    print(f"[posts] 검사 {len(posts)}개", flush=True)
    for p in posts:
        author = p.author
        bm = s.query(Bookmark).filter_by(post_id=p.id).count()
        for u in _post_urls(p):
            if is_private_url(u):
                hits.append((f"posts id={p.id}", f"@{author.username if author else '?'}/{p.number} (북마크 {bm}명)", u))
    for u in s.query(User).all():
        for col, val in (("profile_image", u.profile_image), ("header_image", u.header_image)):
            if is_private_url(val):
                hits.append((f"users id={u.id} {col}", f"@{u.username}", val))
    for e in s.query(CustomEmoji).all():
        if is_private_url(e.source_url):
            hits.append((f"custom_emojis id={e.id}", f":{e.keyword}:", e.source_url))

print()
if not hits:
    print("[결과] 사설 주소 리소스 없음.")
    print("       -> 이 결과면 Firefox 캐시/확장 프로그램 문제이거나, 호스트명을 DNS로 확인해야")
    print("          감지되는 주소입니다. ./gogo.sh check-lna --resolve 로 다시 실행해 보세요.")
    sys.exit(0)

print(f"[결과] 사설 주소 리소스 {len(hits)}건 발견:")
for where, detail, url in hits:
    print(f"  - {where} [{detail}]")
    print(f"      {url}")
print()
print("127.0.0.1 / localhost / 192.168.* / 10.* / 172.16-31.* 로 시작하는 URL이")
print("Firefox LNA 팝업을 유발합니다. 해당 게시글 미디어를 제거하거나 URL을")
print("정상 도메인으로 바꾸면 팝업이 사라집니다.")
PYEOF

elif [ "$1" = "fix-lna" ]; then
  # Firefox LNA 팝업 유발 사설 URL 데이터 정리 (읽기 전용 검사 후, --apply 시 수정)
  # 사용법: ./gogo.sh fix-lna        (검사만)
  #         ./gogo.sh fix-lna --apply (프리뷰 URL/이미지가 사설 주소면 정리 후 커밋)
  APPLY_FLAG="${2:-}"
  docker compose exec -T -e APPLY_FLAG="$APPLY_FLAG" api python3 <<'PYEOF'
import os, ipaddress, re, socket, sys
from urllib.parse import urlparse
import httpx
from app.models import Post
from app.db.database import get_session

apply_ = os.environ.get("APPLY_FLAG") == "--apply"
_PRIVATE_ATTRS = ("is_private", "is_loopback", "is_link_local", "is_reserved")
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".writ")


def _ip_literal(h):
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return any(getattr(ip, a, False) for a in _PRIVATE_ATTRS)


def _resolve_private(h):
    try:
        infos = socket.getaddrinfo(h, None)
    except OSError:
        return False
    return any(_ip_literal(i[4][0]) for i in infos)


def is_private_url(url):
    if not url or not url.startswith("http"):
        return False
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    h = host.strip("[]").lower()
    if h == "localhost" or h.endswith(".localhost") or h in ("0.0.0.0", "::1"):
        return True
    if _ip_literal(h):
        return True
    if h.endswith(_PRIVATE_SUFFIXES):
        return True
    return _resolve_private(h)


def _refresh_image(lp):
    # 링크가 공개 URL인데 이미지만 사설일 때, 다시 fetch해 og:image 재생성
    try:
        resp = httpx.get(lp["url"], headers={"User-Agent": "WRIT/1.0"}, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        html_text = resp.text
        def _og(n):
            m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html_text, re.I)
            if not m:
                m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html_text, re.I)
            return m.group(1) if m else ""
        img = _og("image")
        if not img:
            return None
        if img.startswith("/"):
            p = urlparse(lp["url"])
            img = f"{p.scheme}://{p.netloc}{img}"
        if is_private_url(img):
            return None
        return img
    except Exception:
        return None


changes = []
with get_session() as s:
    posts = s.query(Post).filter(Post.is_deleted == False).order_by(Post.id).limit(20000).all()
    for p in posts:
        if not p.link_preview:
            continue
        lp = p.link_preview
        if is_private_url(lp.get("url")):
            changes.append((f"posts id={p.id}", "link_preview 전체 제거", lp.get("url", "")))
            if apply_:
                p.link_preview = None
        elif lp.get("image") and is_private_url(lp["image"]):
            new_img = _refresh_image(lp) if apply_ else None
            if new_img:
                changes.append((f"posts id={p.id}", "link_preview.image 재생성", f"{lp['image']} -> {new_img}"))
                if apply_:
                    lp["image"] = new_img
                    p.link_preview = lp
            else:
                changes.append((f"posts id={p.id}", "link_preview.image 비움", lp["image"]))
                if apply_:
                    lp["image"] = ""
                    p.link_preview = lp
        for att in (p.media_attachments or []):
            for u in (att.get("url"), att.get("remote_url"), att.get("thumbnail")):
                if u and is_private_url(u):
                    changes.append((f"posts id={p.id}", "media(수동 처리 필요)", u))
    if apply_ and changes:
        s.commit()

print()
if not changes:
    print("[결과] 정리할 사설 주소 데이터 없음.")
    sys.exit(0)
print(f"[결과] 사설 주소 리소스 {len(changes)}건" + (" 수정 완료." if apply_ else " 발견 (--apply 로 수정):"))
seen = set()
for where, kind, url in changes:
    key = (where, kind, url)
    if key in seen:
        continue
    seen.add(key)
    print(f"  - {where}: {kind}")
    print(f"      {url}")
if not apply_:
    print()
    print("./gogo.sh fix-lna --apply 로 link_preview 를 자동 정리할 수 있습니다.")
    print("media_attachments 의 사설 URL은 자동 삭제하지 않으니 수동으로 확인하세요.")
PYEOF

else
  echo ""
  echo "명령어:"
  echo "  check-streams   - SSE 스트림 누적/연결 상태 + web→api 왕복 + 서버 부하 진단"
  echo "  profile-timeline - 타임라인/알림/단건 직렬화 병목 프로파일링 (예: ./gogo.sh profile-timeline siarte home)"
  echo "  fetch-log       - API 로그 확인"
  echo "  rebuild         - 코드 풀 + api 빌드 + 재시작"
  echo "  exec            - 외부 URL 요청 테스트 (path 확인)"
  echo "  key-test        - 서명/키 검증"
  echo "  network-check   - 네트워크 연결 확인"
  echo "  api-test        - API 인박스 직접 테스트"
  echo "  migrate-emojis  - 이모지 파일 local/remote 경로 마이그레이션"
  echo "  fix-follow      - 꼬인 팔로우 강제 수락 및 Accept 전송 (예: ./gogo.sh fix-follow siarte alex@daydream.ink)"
  echo "  dedup-users     - 중복 리모트 유저 통합"
  echo "  purge-deleted   - 스레드에 없는 삭제된 게시글 완전 제거 (댓글 있는 건 껍데기 유지)"
  echo "  purge-orphan    - 내용/부스트/답글/ap_id 없는 고아 포스트 삭제"
  echo "  purge-shadows   - 자기 도메인을 가리키는 그림자 원격 유저 삭제"
  echo "  check-custom-fields - 원격 액터의 attachment/custom_fields 확인 (예: ./gogo.sh check-custom-fields https://daydream.ink/users/siarte)"
  echo "  check-create    - 포스트의 AP Create JSON 출력 (예: ./gogo.sh check-create 5371)"
  echo "  replay-mastodon - 받은 Create를 Mastodon 포맷으로 재전송 (예: ./gogo.sh replay-mastodon 5371 https://qdon.space/inbox)"
  echo "  fix-usernames   - 리모트 유저 username 중복 도메인(user@dom@dom → user@dom) 정리"
  echo "  reprocess-avatars - 기존 아바타 이미지 정사각형 센터크롭 다시 처리"
  echo "  check-lna       - Firefox 로컬 네트워크 접근 팝업 유발 사설 URL 진단 (예: ./gogo.sh check-lna --resolve)"
  echo "  fix-lna         - LNA 유발 사설 URL 데이터 정리 (예: ./gogo.sh fix-lna --apply)"
fi
