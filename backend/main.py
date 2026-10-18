from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
import numpy as np
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from filelock import FileLock
from pydantic import BaseModel, Field

from model_download import ensure_model

DATA = Path(os.getenv('DATA_DIR', Path(__file__).parent / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
SECRET = os.getenv('JWT_SECRET', 'local-demo-secret-change-me-32-bytes-minimum')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@faceaccess.local')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'Admin@123456')
KIOSK_KEY = os.getenv('KIOSK_API_KEY', 'demo-kiosk-key')
THRESHOLD = float(os.getenv('MATCH_THRESHOLD', '0.45'))
INSIGHTFACE_ROOT = os.getenv('INSIGHTFACE_ROOT', str(Path(__file__).parent / 'models'))
INSIGHTFACE_MODEL = os.getenv('INSIGHTFACE_MODEL', 'buffalo_l')
ph = PasswordHasher()
lock = threading.RLock()
disk_lock = FileLock(str(DATA / '.write.lock'))
app = FastAPI(title='FaceAccess API', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['*'], allow_headers=['*'])


@app.on_event('startup')
def prepare_face_model() -> None:
    if face_engine_available():
        ensure_model(INSIGHTFACE_ROOT, INSIGHTFACE_MODEL)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path: Path, value: Any) -> None:
    with lock, disk_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)


def append_log(path: Path, value: dict) -> None:
    with lock, disk_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(value, ensure_ascii=False) + '\n')


def audit(action: str, user: str, member_id: str | None = None) -> None:
    append_log(DATA / 'logs' / 'audit' / (date.today().strftime('%Y-%m') + '.jsonl'), {'at': now(), 'action': action, 'user': user, 'member_id': member_id})


def member_path(member_id: str) -> Path:
    if not all(c in '0123456789abcdef-' for c in member_id.lower()):
        raise HTTPException(404, 'Không tìm thấy hội viên')
    return DATA / 'members' / f'{member_id}.json'


def get_member(member_id: str) -> dict:
    member = read_json(member_path(member_id), None)
    if not member or member.get('deleted_at'):
        raise HTTPException(404, 'Không tìm thấy hội viên')
    return member


def all_members() -> list[dict]:
    return [m for p in (DATA / 'members').glob('*.json') if (m := read_json(p, None)) and not m.get('deleted_at')]


def effective_status(member: dict) -> str:
    if member['status'] != 'active':
        return member['status']
    periods = member.get('memberships', [])
    today = date.today().isoformat()
    if not any(p['start_date'] <= today <= p['end_date'] for p in periods):
        return 'expired'
    return 'active'


def expose(member: dict) -> dict:
    return {**member, 'effective_status': effective_status(member), 'has_face': (DATA / 'faces' / f"{member['id']}.npz").exists()}


def logs() -> list[dict]:
    rows = []
    for path in sorted((DATA / 'logs' / 'access').glob('*.jsonl'), reverse=True):
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(rows, key=lambda row: row['occurred_at'], reverse=True)


def access_log(member: dict | None, direction: str, decision: str, reason: str | None = None, score: float | None = None, manual: bool = False, simulated: bool = False) -> dict:
    row = {'id': str(uuid.uuid4()), 'occurred_at': now(), 'member_id': member['id'] if member else None, 'member_name': member['full_name'] if member else 'Không xác định', 'direction': direction, 'decision': decision, 'reason_code': reason, 'match_score': score, 'device_id': 'door-main', 'is_manual_override': manual, 'simulated': simulated}
    append_log(DATA / 'logs' / 'access' / (date.today().isoformat() + '.jsonl'), row)
    return row


def current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Cần đăng nhập')
    try:
        payload = jwt.decode(authorization[7:], SECRET, algorithms=['HS256'])
        if payload.get('type') != 'access':
            raise ValueError()
        return payload
    except Exception:
        raise HTTPException(401, 'Phiên đăng nhập không hợp lệ')


def admin(user: dict = Depends(current_user)) -> dict:
    if user['role'] != 'admin':
        raise HTTPException(403, 'Cần quyền quản trị')
    return user


def kiosk_key(x_api_key: str | None = Header(None)) -> None:
    if not x_api_key or x_api_key != KIOSK_KEY:
        raise HTTPException(401, 'Kiosk key không hợp lệ')


class Login(BaseModel):
    email: str
    password: str


class MemberIn(BaseModel):
    full_name: str = Field(min_length=2)
    phone: str = Field(min_length=8)
    email: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    notes: str | None = None


class MemberPatch(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


class MembershipIn(BaseModel):
    plan_id: str
    start_date: date = Field(default_factory=date.today)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2)


class PlanIn(BaseModel):
    name: str = Field(min_length=2)
    duration_days: int = Field(gt=0)
    price: int = Field(ge=0)
    allowed_start_time: str | None = None
    allowed_end_time: str | None = None


def seed() -> None:
    if not (DATA / 'staff_users.json').exists():
        write_json(DATA / 'staff_users.json', [{'email': ADMIN_EMAIL, 'password_hash': ph.hash(ADMIN_PASSWORD), 'role': 'admin'}])
    if not (DATA / 'plans.json').exists():
        write_json(DATA / 'plans.json', [{'id': 'plan-standard', 'name': 'Standard', 'duration_days': 30, 'price': 350000, 'is_active': True}, {'id': 'plan-premium', 'name': 'Premium', 'duration_days': 30, 'price': 500000, 'is_active': True}])


seed()


@app.get('/api/v1/health')
def health():
    return {'status': 'ok', 'face_engine': face_engine_available()}


@app.post('/api/v1/auth/login')
def login(body: Login):
    user = next((u for u in read_json(DATA / 'staff_users.json', []) if u['email'].lower() == body.email.lower()), None)
    try:
        valid = bool(user) and ph.verify(user['password_hash'], body.password)
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(401, 'Email hoặc mật khẩu không đúng')
    base = {'sub': user['email'], 'role': user['role']}
    return {'access_token': jwt.encode({**base, 'type': 'access', 'exp': datetime.now(timezone.utc) + timedelta(hours=8)}, SECRET, algorithm='HS256'), 'user': {'email': user['email'], 'role': user['role']}}


@app.get('/api/v1/auth/me')
def me(user: dict = Depends(current_user)):
    return {'email': user['sub'], 'role': user['role']}


@app.get('/api/v1/plans')
def get_plans(_=Depends(current_user)):
    return read_json(DATA / 'plans.json', [])


@app.post('/api/v1/plans')
def create_plan(body: PlanIn, user: dict = Depends(admin)):
    plan = {'id': str(uuid.uuid4()), **body.model_dump(), 'is_active': True}
    plans = read_json(DATA / 'plans.json', [])
    plans.append(plan)
    write_json(DATA / 'plans.json', plans)
    audit('create_plan', user['sub'])
    return plan


@app.get('/api/v1/members')
def list_members(q: str = '', status: str = '', page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _=Depends(current_user)):
    items = [expose(m) for m in all_members() if q.casefold() in (m['full_name'] + m['phone'] + m['member_code']).casefold()]
    if status:
        items = [m for m in items if m['effective_status'] == status]
    items.sort(key=lambda m: m['created_at'], reverse=True)
    return {'items': items[(page-1)*page_size:page*page_size], 'total': len(items), 'page': page}


@app.post('/api/v1/members')
def create_member(body: MemberIn, user: dict = Depends(current_user)):
    with lock, disk_lock:
        meta = read_json(DATA / 'meta.json', {'member_counter': 0})
        meta['member_counter'] += 1
        write_json(DATA / 'meta.json', meta)
        member = {'id': str(uuid.uuid4()), 'member_code': f"MB-{meta['member_counter']:06d}", **body.model_dump(), 'status': 'active', 'suspended_reason': None, 'biometric_consent_at': None, 'consent_version': None, 'memberships': [], 'created_at': now(), 'updated_at': now(), 'deleted_at': None}
        write_json(member_path(member['id']), member)
    audit('create_member', user['sub'], member['id'])
    return expose(member)


@app.get('/api/v1/members/{member_id}')
def member_detail(member_id: str, _=Depends(current_user)):
    return expose(get_member(member_id))


@app.patch('/api/v1/members/{member_id}')
def update_member(member_id: str, body: MemberPatch, user: dict = Depends(current_user)):
    member = get_member(member_id)
    member.update(body.model_dump(exclude_unset=True))
    member['updated_at'] = now()
    write_json(member_path(member_id), member)
    audit('update_member', user['sub'], member_id)
    return expose(member)


@app.delete('/api/v1/members/{member_id}')
def delete_member(member_id: str, user: dict = Depends(admin)):
    member = get_member(member_id)
    member['deleted_at'] = now()
    write_json(member_path(member_id), member)
    (DATA / 'faces' / f'{member_id}.npz').unlink(missing_ok=True)
    audit('delete_member', user['sub'], member_id)
    return {'ok': True}


@app.post('/api/v1/members/{member_id}/suspend')
def suspend(member_id: str, body: ReasonIn, user: dict = Depends(current_user)):
    member = get_member(member_id)
    member.update(status='suspended', suspended_reason=body.reason, updated_at=now())
    write_json(member_path(member_id), member)
    audit('suspend_member', user['sub'], member_id)
    return expose(member)


@app.post('/api/v1/members/{member_id}/unsuspend')
def unsuspend(member_id: str, user: dict = Depends(current_user)):
    member = get_member(member_id)
    member.update(status='active', suspended_reason=None, updated_at=now())
    write_json(member_path(member_id), member)
    audit('unsuspend_member', user['sub'], member_id)
    return expose(member)


@app.post('/api/v1/members/{member_id}/memberships')
def assign_membership(member_id: str, body: MembershipIn, user: dict = Depends(current_user)):
    member = get_member(member_id)
    plan = next((p for p in read_json(DATA / 'plans.json', []) if p['id'] == body.plan_id and p['is_active']), None)
    if not plan:
        raise HTTPException(404, 'Không tìm thấy gói')
    last_end = max((date.fromisoformat(p['end_date']) for p in member['memberships']), default=date.min)
    start = max(body.start_date, last_end + timedelta(days=1)) if last_end >= body.start_date else body.start_date
    member['memberships'].append({'plan_id': plan['id'], 'start_date': start.isoformat(), 'end_date': (start + timedelta(days=plan['duration_days']-1)).isoformat()})
    member['updated_at'] = now()
    write_json(member_path(member_id), member)
    audit('assign_membership', user['sub'], member_id)
    return expose(member)


@app.get('/api/v1/members/{member_id}/access-logs')
def member_logs(member_id: str, _=Depends(current_user)):
    get_member(member_id)
    return [row for row in logs() if row['member_id'] == member_id]


_face_app = None
_recent_recognitions: dict[str, tuple[float, dict]] = {}
def face_engine_available() -> bool:
    try:
        import insightface  # noqa: F401
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def inspect_frame(image: bytes) -> dict:
    global _face_app
    try:
        import cv2
        from insightface.app import FaceAnalysis
    except ImportError:
        raise HTTPException(503, 'Chưa cài InsightFace/ONNX Runtime trên máy chủ')
    if _face_app is None:
        settings = {'name': INSIGHTFACE_MODEL, 'providers': ['CPUExecutionProvider'], 'root': INSIGHTFACE_ROOT, 'allowed_modules': ['detection', 'recognition']}
        _face_app = FaceAnalysis(**settings)
        _face_app.prepare(ctx_id=-1, det_size=(640, 640))
    frame = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(422, 'Ảnh không hợp lệ')
    faces = _face_app.get(frame)
    if not faces:
        return {'face_detected': False, 'quality_ok': False, 'message': 'Không phát hiện khuôn mặt'}
    if len(faces) != 1:
        return {'face_detected': False, 'quality_ok': False, 'message': 'Chỉ một người đứng trước camera'}
    face = faces[0]
    x1, y1, x2, y2 = face.bbox
    x1, y1, x2, y2 = (int(x1), int(y1), int(x2), int(y2))
    eyes = face.kps[:2]
    eye_width = max(float(abs(eyes[1][0] - eyes[0][0])), 1.0)
    yaw = float((face.kps[2][0] - (eyes[0][0] + eyes[1][0]) / 2) / eye_width)
    pose = 'left' if yaw >= 0.18 else 'right' if yaw <= -0.18 else 'front' if abs(yaw) <= 0.12 else 'transition'
    crop = frame[max(0,y1):min(frame.shape[0],y2), max(0,x1):min(frame.shape[1],x2)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else None
    brightness = float(gray.mean()) if gray is not None else 0.0
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray is not None else 0.0
    quality_ok = min(x2-x1, y2-y1) >= 80 and brightness >= 45 and sharpness >= 25
    message = 'Khuôn mặt quá nhỏ' if min(x2-x1, y2-y1) < 80 else 'Ánh sáng quá yếu' if brightness < 45 else 'Ảnh chưa đủ nét' if sharpness < 25 else 'Đạt'
    emb = face.normed_embedding.astype(np.float32)
    return {'face_detected': True, 'quality_ok': quality_ok, 'message': message, 'bbox': [x1, y1, x2, y2], 'image_width': int(frame.shape[1]), 'image_height': int(frame.shape[0]), 'pose': pose, 'yaw': round(yaw, 3), 'embedding': emb / np.linalg.norm(emb)}


@app.post('/api/v1/faces/analyze')
async def analyze(image: UploadFile = File(...), _=Depends(current_user)):
    raw = await image.read()
    if len(raw) > 5_000_000:
        raise HTTPException(422, 'Ảnh quá lớn')
    result = inspect_frame(raw)
    return {key: value for key, value in result.items() if key != 'embedding'}


@app.post('/api/v1/members/{member_id}/faces')
async def enroll_faces(member_id: str, consent: bool = Form(...), images: list[UploadFile] = File(...), user: dict = Depends(current_user)):
    if not consent:
        raise HTTPException(422, 'Cần sự đồng ý của hội viên')
    if not 3 <= len(images) <= 5:
        raise HTTPException(422, 'Cần từ 3 đến 5 ảnh')
    member = get_member(member_id)
    vectors = []
    expected_poses = ['front', 'left', 'right']
    for image in images:
        raw = await image.read()
        if len(raw) > 5_000_000:
            raise HTTPException(422, 'Mỗi ảnh phải nhỏ hơn 5 MB')
        inspected = inspect_frame(raw)
        if not inspected['face_detected'] or not inspected['quality_ok']:
            raise HTTPException(422, inspected['message'])
        if len(vectors) < 3 and inspected['pose'] != expected_poses[len(vectors)]:
            raise HTTPException(422, f"Ảnh {len(vectors)+1} cần đúng hướng {expected_poses[len(vectors)]}")
        if vectors and float(inspected['embedding'] @ vectors[0]) < 0.25:
            raise HTTPException(422, 'Các ảnh cần thuộc cùng một hội viên')
        vectors.append(inspected['embedding'])
    for other in all_members():
        if other['id'] == member_id:
            continue
        path = DATA / 'faces' / f"{other['id']}.npz"
        if path.exists():
            with np.load(path) as item:
                if float(np.max(np.array(vectors) @ item['embeddings'].T)) >= 0.75:
                    raise HTTPException(409, f"Khuôn mặt có thể đã thuộc {other['member_code']}")
    path = DATA / 'faces' / f'{member_id}.npz'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp.npz')
    np.savez_compressed(tmp, embeddings=np.array(vectors, dtype=np.float32), poses=np.array(['front', 'left', 'right'] + ['extra'] * (len(vectors)-3)), created_at=np.array([now()] * len(vectors)))
    os.replace(tmp, path)
    member.update(biometric_consent_at=now(), consent_version='1.0', updated_at=now())
    write_json(member_path(member_id), member)
    audit('enroll_face', user['sub'], member_id)
    return {'ok': True, 'samples': len(vectors)}


@app.delete('/api/v1/members/{member_id}/faces')
def delete_face(member_id: str, user: dict = Depends(current_user)):
    member = get_member(member_id)
    (DATA / 'faces' / f'{member_id}.npz').unlink(missing_ok=True)
    member.update(biometric_consent_at=None, consent_version=None, updated_at=now())
    write_json(member_path(member_id), member)
    audit('delete_face', user['sub'], member_id)
    return {'ok': True}


def decide(member: dict | None, direction: str, score: float | None = None, simulated: bool = False) -> dict:
    if member is None:
        return access_log(None, direction, 'UNKNOWN', 'UNKNOWN_FACE', score, simulated=simulated)
    today = date.today().isoformat()
    has_valid_membership = any(
        item['start_date'] <= today <= item['end_date']
        for item in member.get('memberships', [])
    )
    if not has_valid_membership:
        return access_log(member, direction, 'DENY', 'MEMBERSHIP_EXPIRED', score, simulated=simulated)
    return access_log(member, direction, 'ALLOW', None, score, simulated=simulated)


def member_display(member: dict | None) -> dict:
    if not member:
        return {'member_name': 'Không định danh', 'plan_name': None, 'days_remaining': None, 'membership_end_date': None}
    memberships = member.get('memberships', [])
    today = date.today().isoformat()
    current = next((item for item in memberships if item['start_date'] <= today <= item['end_date']), None)
    if current is None and memberships:
        current = max(memberships, key=lambda item: item['end_date'])
    plan = next((p for p in read_json(DATA / 'plans.json', []) if current and p['id'] == current['plan_id']), None)
    days = max(0, (date.fromisoformat(current['end_date']) - date.today()).days + 1) if current else None
    return {'member_name': member['full_name'], 'plan_name': plan['name'] if plan else None, 'days_remaining': days, 'membership_end_date': current['end_date'] if current else None}


def recognized_decision(member: dict | None, direction: str, score: float | None = None, simulated: bool = False, encounter_id: str = '') -> dict:
    key = f"{int(simulated)}:{direction}:{encounter_id}:{member['id'] if member else 'unknown'}"
    cached = _recent_recognitions.get(key)
    moment = time.monotonic()
    if cached and (encounter_id or moment - cached[0] < 10):
        return cached[1]
    if len(_recent_recognitions) >= 1000:
        oldest = min(_recent_recognitions, key=lambda item: _recent_recognitions[item][0])
        del _recent_recognitions[oldest]
    result = {**decide(member, direction, score, simulated), **member_display(member)}
    _recent_recognitions[key] = (moment, result)
    return result


@app.post('/api/v1/access/recognize')
async def recognize(direction: str = Form('IN'), encounter_id: str = Form(''), image: UploadFile = File(...), _=Depends(kiosk_key)):
    if direction not in ('IN', 'OUT'):
        raise HTTPException(422, 'Hướng không hợp lệ')
    raw = await image.read()
    if len(raw) > 5_000_000:
        raise HTTPException(422, 'Ảnh quá lớn')
    inspected = inspect_frame(raw)
    if not inspected['face_detected']:
        return {'decision': 'RETRY', 'face_detected': False, 'message': inspected['message']}
    box = {'face_detected': True, 'bbox': inspected['bbox'], 'image_width': inspected['image_width'], 'image_height': inspected['image_height']}
    if not inspected['quality_ok']:
        return {'decision': 'RETRY', 'message': inspected['message'], **box}
    emb = inspected['embedding']
    best, score = None, -1.0
    for member in all_members():
        path = DATA / 'faces' / f"{member['id']}.npz"
        if path.exists():
            with np.load(path) as item:
                current = float(np.max(item['embeddings'] @ emb))
            if current > score:
                best, score = member, current
    return {**recognized_decision(best if score >= THRESHOLD else None, direction, round(score, 3), encounter_id=encounter_id[:80]), **box}


@app.post('/api/v1/access/simulate')
async def simulate(image: UploadFile = File(...), member_id: str | None = Form(None), direction: str = Form('IN'), encounter_id: str = Form(''), user: dict = Depends(current_user)):
    if direction not in ('IN', 'OUT'):
        raise HTTPException(422, 'Hướng không hợp lệ')
    raw = await image.read()
    if len(raw) > 5_000_000:
        raise HTTPException(422, 'Ảnh quá lớn')
    inspected = inspect_frame(raw)
    if not inspected['face_detected']:
        return {'decision': 'RETRY', 'face_detected': False, 'message': inspected['message'], 'simulated': True}
    box = {'face_detected': True, 'bbox': inspected['bbox'], 'image_width': inspected['image_width'], 'image_height': inspected['image_height']}
    if not inspected['quality_ok']:
        return {'decision': 'RETRY', 'message': inspected['message'], 'simulated': True, **box}
    member = get_member(member_id) if member_id else None
    result = recognized_decision(member, direction, simulated=True, encounter_id=encounter_id[:80])
    if result.get('id'):
        audit('simulate_access', user['sub'], member_id)
    return {**result, **box}


@app.get('/api/v1/access/logs')
def list_logs(direction: str = '', decision: str = '', member_id: str = '', start: str = '', end: str = '', _=Depends(current_user)):
    return [r for r in logs() if (not direction or r['direction'] == direction) and (not decision or r['decision'] == decision) and (not member_id or r['member_id'] == member_id) and (not start or r['occurred_at'][:10] >= start) and (not end or r['occurred_at'][:10] <= end)]


@app.get('/api/v1/access/logs.csv')
def export_logs(_=Depends(current_user)):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=['occurred_at', 'member_name', 'direction', 'decision', 'reason_code', 'match_score', 'device_id', 'simulated'])
    writer.writeheader()
    for row in logs():
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return StreamingResponse(iter([out.getvalue().encode('utf-8-sig')]), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="access-logs.csv"'})


@app.get('/api/v1/dashboard')
def dashboard(_=Depends(current_user)):
    today = date.today().isoformat()
    events = [r for r in logs() if r['occurred_at'][:10] == today]
    incoming = [r for r in events if r['direction'] == 'IN' and r['decision'] == 'ALLOW']
    rejected = [r for r in events if r['decision'] in ('DENY', 'UNKNOWN')]
    occupancy = {}
    for row in reversed(logs()):
        if row['decision'] == 'ALLOW' and row['member_id']:
            occupancy[row['member_id']] = row['direction']
    soon = sum(1 for m in all_members() if m['memberships'] and 0 <= (date.fromisoformat(max(p['end_date'] for p in m['memberships'])) - date.today()).days <= 7)
    return {'entries': len(incoming), 'occupancy': sum(d == 'IN' for d in occupancy.values()), 'rejection_rate': round(100*len(rejected)/len(events)) if events else 0, 'expiring_soon': soon, 'hourly': [sum(r['occurred_at'][11:13] == f'{hour:02d}' for r in incoming) for hour in range(6, 22, 2)], 'recent': events[:5]}
