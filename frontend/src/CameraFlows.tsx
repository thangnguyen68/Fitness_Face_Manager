import { useEffect, useRef, useState, type RefObject } from 'react'
import { Camera, Check, ShieldCheck, X } from 'lucide-react'

type Membership = { plan_id: string; start_date: string; end_date: string }
export type CameraMember = { id: string; member_code: string; full_name: string; memberships: Membership[] }
type Vision = {
  face_detected: boolean
  quality_ok?: boolean
  message?: string
  pose?: 'front' | 'left' | 'right' | 'transition'
  bbox?: [number, number, number, number]
  image_width?: number
  image_height?: number
  decision?: string
  reason_code?: string
  member_id?: string
  member_name?: string
  plan_name?: string | null
  days_remaining?: number | null
  membership_end_date?: string | null
  simulated?: boolean
  id?: string
}

const root = '/api/v1'
const token = () => localStorage.getItem('faceaccess-token') || ''
async function request<T>(path: string, form: FormData, kiosk = false): Promise<T> {
  const headers: Record<string, string> = kiosk
    ? { 'X-API-Key': import.meta.env.VITE_KIOSK_API_KEY || 'demo-kiosk-key' }
    : { Authorization: `Bearer ${token()}` }
  const response = await fetch(root + path, { method: 'POST', headers, body: form })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `Lỗi ${response.status}`)
  return payload as T
}

function useLiveCamera() {
  const video = useRef<HTMLVideoElement>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let current: MediaStream | null = null
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Camera chỉ hoạt động trên localhost hoặc HTTPS.')
      return
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 }, audio: false })
      .then(value => { current = value; if (active) setStream(value); else value.getTracks().forEach(track => track.stop()) })
      .catch(() => setError('Không mở được camera. Hãy kiểm tra quyền truy cập camera.'))
    return () => { active = false; current?.getTracks().forEach(track => track.stop()) }
  }, [])
  useEffect(() => { if (video.current && stream) video.current.srcObject = stream }, [stream])
  async function capture(): Promise<Blob> {
    const element = video.current
    if (!element || !element.videoWidth || !stream?.active) throw new Error('Camera chưa sẵn sàng')
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = Math.round(640 * element.videoHeight / element.videoWidth)
    canvas.getContext('2d')?.drawImage(element, 0, 0, canvas.width, canvas.height)
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Không chụp được khung hình')), 'image/jpeg', 0.84))
  }
  return { video, stream, error, capture }
}

function FaceBox({ vision, video, label }: { vision: Vision | null; video: RefObject<HTMLVideoElement>; label: string }) {
  const [, resize] = useState(0)
  useEffect(() => {
    const element = video.current
    if (!element) return
    const observer = new ResizeObserver(() => resize(value => value + 1))
    observer.observe(element)
    return () => observer.disconnect()
  }, [video])
  if (!vision?.face_detected || !vision.bbox || !vision.image_width || !vision.image_height || !video.current) return null
  const width = video.current.clientWidth
  const height = video.current.clientHeight
  const scale = Math.min(width / vision.image_width, height / vision.image_height)
  const offsetX = (width - vision.image_width * scale) / 2
  const offsetY = (height - vision.image_height * scale) / 2
  const [x1, y1, x2, y2] = vision.bbox
  const left = width - (offsetX + x2 * scale)
  const top = offsetY + y1 * scale
  return <div className="detected-face" style={{ left, top, width: (x2-x1)*scale, height: (y2-y1)*scale }}><span>{label}</span></div>
}

const poses = ['front', 'left', 'right'] as const
const poseLabels = ['Nhìn thẳng', 'Quay nhẹ sang trái', 'Quay nhẹ sang phải']
export function AutoEnroll({ members, selected, setSelected, busy, onSaved }: {
  members: CameraMember[]
  selected: CameraMember | null
  setSelected: (member: CameraMember | null) => void
  busy: boolean
  onSaved: () => void
}) {
  const { video, stream, error: cameraError, capture } = useLiveCamera()
  const [shots, setShots] = useState<Blob[]>([])
  const [vision, setVision] = useState<Vision | null>(null)
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [savedMessage, setSavedMessage] = useState('')
  const stable = useRef(0)
  useEffect(() => { setShots([]); setConsent(false); setVision(null); setCompleted(false); setSavedMessage(''); stable.current = 0 }, [selected?.id])
  useEffect(() => {
    if (!stream || !selected || shots.length >= 3 || saving || completed) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    stable.current = 0
    const loop = async () => {
      try {
        const frame = await capture()
        const form = new FormData()
        form.append('image', frame, 'frame.jpg')
        const found = await request<Vision>('/faces/analyze', form)
        if (!active) return
        setVision(found)
        setError('')
        if (found.face_detected && found.quality_ok && found.pose === poses[shots.length]) {
          stable.current += 1
          if (stable.current >= 2) {
            setShots(previous => previous.length === shots.length ? [...previous, frame] : previous)
            return
          }
        } else stable.current = 0
      } catch (cause) { if (active) { setError((cause as Error).message); setVision(null) } }
      if (active) timer = setTimeout(loop, 350)
    }
    timer = setTimeout(loop, 300)
    return () => { active = false; clearTimeout(timer) }
  }, [stream, selected?.id, shots.length, saving, completed])
  async function save() {
    if (!selected || shots.length !== 3 || !consent) return
    setSaving(true)
    try {
      const form = new FormData()
      form.append('consent', 'true')
      shots.forEach((shot, index) => form.append('images', shot, `${poses[index]}.jpg`))
      await request(`/members/${selected.id}/faces`, form)
      setShots([])
      setCompleted(true)
      setSavedMessage('Đã lưu khuôn mặt thành công')
      onSaved()
    } catch (cause) {
      setError((cause as Error).message)
    } finally { setSaving(false) }
  }
  const instruction = !selected ? 'Chọn hội viên để bắt đầu' : completed ? 'Đã lưu khuôn mặt' : shots.length >= 3 ? 'Đã tự chụp đủ 3 hướng' : `Bước ${shots.length+1}/3: ${poseLabels[shots.length]}`
  return <>
    <div className="page-heading"><div><div className="eyebrow">SINH TRẮC HỌC</div><h1>Đăng ký khuôn mặt</h1><p>Camera tự kiểm tra hướng mặt và tự chụp khi đạt yêu cầu.</p></div></div>
    <div className="enroll-grid">
      <div className="card auto-enroll-card">
        <label>Chọn hội viên<select value={selected?.id || ''} onChange={event => setSelected(members.find(member => member.id === event.target.value) || null)}><option value="">Chọn hội viên...</option>{members.map(member => <option key={member.id} value={member.id}>{member.member_code} · {member.full_name}</option>)}</select></label>
        <div className="camera-box"><video ref={video} autoPlay playsInline muted/><FaceBox vision={vision} video={video} label={vision?.pose === 'front' ? 'Nhìn thẳng' : vision?.pose === 'left' ? 'Nghiêng trái' : vision?.pose === 'right' ? 'Nghiêng phải' : 'Đang canh chỉnh'}/>{!stream && <div className="camera-placeholder camera-wait"><Camera size={40}/><span>Đang mở camera</span></div>}</div>
        <div className="camera-instruction"><span className={shots.length >= 3 ? 'live-dot' : 'pulse-dot'}/><strong>{instruction}</strong></div>
        {selected && vision?.face_detected && !vision.quality_ok && <p className="field-error">{vision.message}</p>}
        {(cameraError || error) && <p className="field-error">{cameraError || error}</p>}
        {savedMessage && <p className="save-message">{savedMessage}</p>}
      </div>
      <div className="enroll-side"><div className="card"><div className="eyebrow">TIẾN ĐỘ ĐĂNG KÝ</div><h2>{completed ? 3 : shots.length}/3 ảnh đã chụp tự động</h2><div className="steps">{poseLabels.map((label, index) => <div className="step" key={label}><div className={`step-num ${index < shots.length || completed ? 'done' : ''}`}>{index < shots.length || completed ? <Check size={16}/> : index + 1}</div><span>{label}</span>{(index < shots.length || completed) && <span className="badge good">Đã chụp</span>}</div>)}</div><button className="text-button" onClick={() => { setShots([]); setCompleted(false); setSavedMessage('') }}>Chụp lại từ đầu</button></div><div className="card"><label className="checkbox"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/><span>Hội viên đồng ý thu thập và xử lý dữ liệu khuôn mặt để kiểm soát ra vào (điều khoản v1.0).</span></label><button className="btn primary full" disabled={!selected || shots.length !== 3 || !consent || busy || saving || completed} onClick={save}>Lưu khuôn mặt</button><p className="help">Ảnh chụp chỉ dùng để tạo vector đặc trưng, không lưu ảnh gốc.</p></div></div>
    </div>
  </>
}

const reasons: Record<string, string> = { MEMBERSHIP_EXPIRED: 'Gói đã hết hạn', MEMBER_SUSPENDED: 'Hội viên bị khóa', MEMBER_INACTIVE: 'Hội viên ngưng hoạt động', ANTI_PASSBACK: 'Đã vào, chưa ghi nhận ra', UNKNOWN_FACE: 'Không xác định hội viên', COOLDOWN: 'Vừa ghi nhận lượt này' }
export function AutoKiosk({ members, onResult }: { members: CameraMember[]; onResult: () => void }) {
  const { video, stream, error: cameraError, capture } = useLiveCamera()
  const [direction, setDirection] = useState<'IN' | 'OUT'>('IN')
  const [mode, setMode] = useState<'camera' | 'simulate'>('camera')
  const [memberId, setMemberId] = useState('')
  const [vision, setVision] = useState<Vision | null>(null)
  const [error, setError] = useState('')
  const lastEvent = useRef('')
  const session = useRef(crypto.randomUUID())
  const encounter = useRef(0)
  const faceWasPresent = useRef(false)
  const missingFrames = useRef(0)
  useEffect(() => {
    if (!stream) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    setVision(null)
    encounter.current += 1
    faceWasPresent.current = false
    missingFrames.current = 0
    const loop = async () => {
      try {
        const frame = await capture()
        const form = new FormData()
        form.append('image', frame, 'frame.jpg')
        form.append('direction', direction)
        form.append('encounter_id', `${session.current}:${encounter.current}`)
        if (mode === 'simulate' && memberId) form.append('member_id', memberId)
        const result = await request<Vision>(mode === 'camera' ? '/access/recognize' : '/access/simulate', form, mode === 'camera')
        if (!active) return
        if (result.face_detected) {
          missingFrames.current = 0
          faceWasPresent.current = true
        } else if (faceWasPresent.current) {
          missingFrames.current += 1
          if (missingFrames.current >= 3) {
            encounter.current += 1
            faceWasPresent.current = false
            missingFrames.current = 0
          }
        }
        setVision(result.face_detected ? result : null)
        setError('')
        if (result.id && result.id !== lastEvent.current) { lastEvent.current = result.id; onResult() }
      } catch (cause) { if (active) { setError((cause as Error).message); setVision(null) } }
      if (active) timer = setTimeout(loop, 650)
    }
    timer = setTimeout(loop, 150)
    return () => { active = false; clearTimeout(timer) }
  }, [stream, direction, mode, memberId])
  const found = vision?.face_detected
  const identified = !!vision?.member_id
  const label = identified ? vision?.member_name || 'Hội viên' : 'Không định danh'
  const state = found && vision?.decision !== 'RETRY' ? vision?.decision?.toLowerCase() || '' : ''
  return <div className="kiosk-page">
    <div className="kiosk-top"><div><div className="eyebrow">CỬA CHÍNH / {direction === 'IN' ? 'VÀO' : 'RA'}</div><h1>Màn hình Kiosk</h1><p className="muted">Tự động nhận diện khi có người trước camera.</p></div><div className="kiosk-switch"><button className={direction === 'IN' ? 'chosen' : ''} onClick={() => setDirection('IN')}>VÀO</button><button className={direction === 'OUT' ? 'chosen' : ''} onClick={() => setDirection('OUT')}>RA</button></div></div>
    <div className="kiosk-grid"><div className="kiosk-view"><div className="camera-box kiosk-camera"><video ref={video} autoPlay playsInline muted/><FaceBox vision={vision} video={video} label={label}/>{!stream && <div className="camera-placeholder camera-wait"><Camera size={42}/><span>Đang mở camera</span></div>}</div><div className="camera-caption"><span className="live-dot"/>{stream ? 'Camera đang tự động quét' : cameraError || 'Đang kết nối camera...'}</div></div>
      <div className={`kiosk-result ${state}`}><div className="eyebrow">KẾT QUẢ KIỂM SOÁT</div>{found ? <><div className="result-icon">{vision?.decision === 'ALLOW' ? <Check size={38}/> : <X size={38}/>}</div><h2>{vision?.decision === 'ALLOW' ? 'Được phép vào' : vision?.decision === 'DENY' || vision?.decision === 'UNKNOWN' ? 'Từ chối' : vision?.decision === 'DUPLICATE' ? 'Đã ghi nhận' : 'Đang canh chỉnh'}</h2><h3>{label}</h3>{identified && <p className="plan-days">{vision?.plan_name || 'Chưa có gói'} · Còn {vision?.days_remaining ?? 0} ngày</p>}<p>{reasons[vision?.reason_code || ''] || vision?.message || (vision?.decision === 'ALLOW' ? 'Vui lòng di chuyển qua cửa' : 'Vui lòng nhìn thẳng vào camera')}</p>{vision?.simulated && <span className="sim-badge">KẾT QUẢ MÔ PHỎNG</span>}</> : <><div className="waiting-icon"><ShieldCheck size={40}/></div><h2>Sẵn sàng nhận diện</h2><p>Hãy nhìn vào camera.</p></>}</div>
    </div>
    <div className="kiosk-controls card"><div className="segmented"><button className={mode === 'camera' ? 'chosen' : ''} onClick={() => setMode('camera')}>Nhận diện thật</button><button className={mode === 'simulate' ? 'chosen' : ''} onClick={() => setMode('simulate')}>Mô phỏng</button></div>{mode === 'simulate' && <select value={memberId} onChange={event => setMemberId(event.target.value)} aria-label="Hội viên mô phỏng"><option value="">Không định danh</option>{members.map(member => <option key={member.id} value={member.id}>{member.member_code} · {member.full_name}</option>)}</select>}{error && <p className="field-error">{error}</p>}<p className="help">Hệ thống tự quét khi camera hoạt động. Chế độ mô phỏng được ghi nhãn riêng trong nhật ký.</p></div>
  </div>
}
