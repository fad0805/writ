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
fi
