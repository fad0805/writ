"""Seed data for development/testing. Not used in production."""

from app.models import User, Post, Follow, Novel, Episode, get_session
from app.config import BASE_URL, SECRET_KEY


def seed_default_data():
    from app.routes.auth import hash_password
    from app.crypto_utils import generate_keypair as gen_kp, encrypt_key

    with get_session() as session:
        existing = session.query(User).filter_by(username="author1").first()
        if existing:
            for u in [existing, session.query(User).filter_by(username="reader1").first(), session.query(User).filter_by(username="admin").first()]:
                if u and not u.email_verified:
                    u.email_verified = True
            session.commit()
            return

        priv, pub = gen_kp()
        salt, hsh = hash_password("test1234")
        author1 = User(
            username="author1", display_name="소설가 author1",
            password_hash=salt + ":" + hsh,
            private_key=encrypt_key(priv, SECRET_KEY), public_key=pub,
            summary="소설을 쓰는 사람입니다 ✍️",
            role="user",
            email="author1@example.com",
            email_verified=True,
        )
        session.add(author1)
        session.flush()

        priv2, pub2 = gen_kp()
        salt2, hsh2 = hash_password("test1234")
        reader1 = User(
            username="reader1", display_name="독자 reader1",
            password_hash=salt2 + ":" + hsh2,
            private_key=encrypt_key(priv2, SECRET_KEY), public_key=pub2,
            summary="소설 읽는 걸 좋아합니다 📖",
            role="user",
            email="reader1@example.com",
            email_verified=True,
        )
        session.add(reader1)
        session.flush()

        priv3, pub3 = gen_kp()
        admin_password = "admin1234"
        salt3, hsh3 = hash_password(admin_password)
        admin_user = User(
            username="admin", display_name="관리자",
            password_hash=salt3 + ":" + hsh3,
            private_key=encrypt_key(priv3, SECRET_KEY), public_key=pub3,
            summary="서버 관리자입니다",
            role="admin",
            is_admin=True,
            email="admin@example.com",
            email_verified=True,
        )
        session.add(admin_user)
        session.flush()

        print(f"✅ Admin account created: admin / {admin_password}")

        priv4, pub4 = gen_kp()
        owner_password = "owner1234"
        salt4, hsh4 = hash_password(owner_password)
        owner_user = User(
            username="owner", display_name="오너",
            password_hash=salt4 + ":" + hsh4,
            private_key=encrypt_key(priv4, SECRET_KEY), public_key=pub4,
            summary="소유주 계정입니다",
            role="owner",
            is_admin=True,
            email="owner@example.com",
            email_verified=True,
        )
        session.add(owner_user)
        session.flush()

        priv5, pub5 = gen_kp()
        mod_password = "mod1234"
        salt5, hsh5 = hash_password(mod_password)
        mod_user = User(
            username="moderator", display_name="조율자",
            password_hash=salt5 + ":" + hsh5,
            private_key=encrypt_key(priv5, SECRET_KEY), public_key=pub5,
            summary="조율자 계정입니다",
            role="moderator",
            email="moderator@example.com",
            email_verified=True,
        )
        session.add(mod_user)
        session.flush()

        print(f"✅ Owner account created: owner / {owner_password}")
        print(f"✅ Moderator account created: moderator / {mod_password}")

        p1 = Post(author_id=author1.id, content="안녕하세요, 소설을 시작합니다!", visibility="public", number="a1b2c3d4")
        p2 = Post(author_id=author1.id, content="오늘은 첫 번째 에피소드를 썼어요.", visibility="home", number="e5f6g7h8")
        session.add_all([p1, p2])

        novel1 = Novel(author_id=author1.id, title="판타지 세계로", description="이세계 판타지 소설입니다", tags="판타지,이세계")
        novel2 = Novel(author_id=author1.id, title="일상의 기록", description="일상물 에세이", tags="일상,에세이")
        session.add_all([novel1, novel2])
        session.flush()

        ep1 = Episode(novel_id=novel1.id, episode_number=1, title="프롤로그", content="모든 이야기는 그렇게 시작되었다...")
        ep2 = Episode(novel_id=novel1.id, episode_number=2, title="첫 만남", content="드디어 주인공이 나타났다.")
        session.add_all([ep1, ep2])

        follow = Follow(follower_id=reader1.id, following_id=author1.id, accepted=True)
        session.add(follow)

        p3 = Post(author_id=reader1.id, content="재미있는 소설 추천 받아요!", visibility="public", number="i9j0k1l2")
        session.add(p3)

        user_map = {author1.id: author1, reader1.id: reader1, admin_user.id: admin_user}
        for post in [p1, p2, p3]:
            u = user_map.get(post.author_id)
            if u:
                post.ap_id = f"{BASE_URL}/@{u.username}/{post.number}"

        session.commit()
