import re
from fastapi import APIRouter
from models import User, Post, Follow, get_session

router = APIRouter()

NOTIF_FILTERS = sorted({
    "follow", "like", "boost", "mention",
})
